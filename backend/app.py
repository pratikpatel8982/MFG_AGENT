"""
backend/app.py — Flask application factory + all API routes.

Routes:
  GET  /                         → serve frontend
  POST /api/query                → SSE streaming pipeline  [auth required]
  POST /api/stop                 → cancel running pipeline [auth required]
  GET  /api/history              → user query history      [auth required]
  GET  /api/reports              → user's saved reports    [auth required]
  GET  /api/report/<session_id>  → single report           [auth required]
  GET  /api/suppliers/search     → semantic supplier search [auth required]
  GET  /api/suppliers            → all user suppliers      [auth required]
  GET  /api/download/<session_id>      → text download     [auth required]
  GET  /api/download-json/<session_id> → JSON download     [auth required]
  GET  /api/health               → public health check
  GET  /api/stats                → DB stats                [auth required]
"""
import json
import queue as _queue
import sys
import threading

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.config import cfg
from backend.agents import ManufacturingOrchestrator, StreamLogger
from backend.agents.state import request_stop
from backend.auth import require_auth, optional_auth
from backend.db.chroma import get_store


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static", static_url_path="")
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    orchestrator = ManufacturingOrchestrator()

    # ── Static / Frontend ─────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/app.html")
    def app_page():
        return send_from_directory(app.static_folder, "app.html")

    @app.route("/<path:path>")
    def static_files(path):
        import os
        full = os.path.join(app.static_folder, path)
        if os.path.isfile(full):
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, "index.html")

    # ── Query (SSE streaming) ─────────────────────────────────────────────────

    @app.route("/api/query", methods=["POST"])
    @require_auth
    def query_endpoint(user: dict):
        body       = request.get_json(force=True)
        user_query = (body.get("query") or "").strip()
        if not user_query:
            return jsonify({"error": "query is required"}), 400

        uid   = user["uid"]
        q     = _queue.Queue()
        logger = StreamLogger(queue=q)

        def run_pipeline():
            try:
                state = orchestrator.run(user_query, logger, user_id=uid)
                # Persist to ChromaDB after run completes
                try:
                    store = get_store()
                    store.log_query(uid, user_query, state.session_id)
                    store.save_suppliers(
                        state.session_id, uid, user_query, state.raw_results
                    )
                    store.save_report(
                        {**state.to_dict(), "product": state.parsed_product,
                         "location": state.parsed_location},
                        elapsed=0,
                    )
                except Exception as db_err:
                    logger.log(f"DB save error (non-fatal): {db_err}", "warn")
            except Exception as e:
                logger.error(f"Pipeline error: {e}")
            finally:
                q.put(None)

        threading.Thread(target=run_pipeline, daemon=True).start()

        def generate():
            while True:
                item = q.get()
                if item is None:
                    break
                yield f"data: {item}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # ── Stop ──────────────────────────────────────────────────────────────────

    @app.route("/api/stop", methods=["POST"])
    @require_auth
    def stop_endpoint(user: dict):
        body       = request.get_json(force=True)
        session_id = (body.get("session_id") or "").strip()
        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        found = request_stop(session_id)
        return jsonify({"stopped": found, "session_id": session_id})

    # ── History ───────────────────────────────────────────────────────────────

    @app.route("/api/history")
    @require_auth
    def history_endpoint(user: dict):
        limit = min(int(request.args.get("limit", 20)), 100)
        try:
            items = get_store().get_user_history(user["uid"], limit=limit)
        except Exception as e:
            items = []
        return jsonify({"history": items})

    # ── Reports ───────────────────────────────────────────────────────────────

    @app.route("/api/reports")
    @require_auth
    def reports_endpoint(user: dict):
        limit = min(int(request.args.get("limit", 20)), 100)
        try:
            items = get_store().get_user_reports(user["uid"], limit=limit)
        except Exception as e:
            items = []
        return jsonify({"reports": items})

    @app.route("/api/report/<session_id>", methods=["GET", "DELETE"])
    @require_auth
    def single_report_endpoint(user: dict, session_id: str):
        try:
            data = get_store().get_report(session_id)
        except Exception:
            data = None
        if not data:
            return jsonify({"error": "Report not found"}), 404
        if data.get("user_id") and data["user_id"] != user["uid"]:
            return jsonify({"error": "Forbidden"}), 403

        if request.method == "DELETE":
            try:
                get_store().delete_report(session_id)
            except Exception:
                pass
            return jsonify({"deleted": session_id})

        return jsonify(data)

    # ── Suppliers ─────────────────────────────────────────────────────────────

    @app.route("/api/suppliers/search")
    @require_auth
    def search_suppliers_endpoint(user: dict):
        q    = request.args.get("q", "").strip()
        n    = min(int(request.args.get("n", 20)), 100)
        if not q:
            return jsonify({"error": "q is required"}), 400
        try:
            results = get_store().search_suppliers(q, user_id=user["uid"], n_results=n)
        except Exception as e:
            results = []
        return jsonify({"suppliers": results, "query": q})

    @app.route("/api/suppliers")
    @require_auth
    def suppliers_endpoint(user: dict):
        limit      = min(int(request.args.get("limit", 100)), 500)
        session_id = request.args.get("session_id", "").strip()
        try:
            items = get_store().get_user_suppliers(
                user["uid"], limit=limit, session_id=session_id or None
            )
        except Exception as e:
            items = []
        return jsonify({"suppliers": items})

    # ── Downloads ─────────────────────────────────────────────────────────────
    # Downloads use ?token= query param because window.open / <a> can't set
    # Authorization headers. Token is still verified server-side — same security.

    def _auth_download(session_id: str):
        """Shared auth + data fetch for download endpoints."""
        from backend.auth.firebase import verify_token as _verify
        token = request.args.get("token", "").strip()
        if not token:
            return None, None, (jsonify({"error": "Missing token"}), 401)
        user = _verify(token)
        if not user:
            return None, None, (jsonify({"error": "Invalid or expired token"}), 401)
        try:
            data = get_store().get_report(session_id)
        except Exception:
            data = None
        if not data:
            return None, None, (jsonify({"error": "Report not found"}), 404)
        if data.get("user_id") and data["user_id"] != user["uid"]:
            return None, None, (jsonify({"error": "Forbidden"}), 403)
        return user, data, None

    @app.route("/api/download/<session_id>")
    def download_txt(session_id: str):
        from flask import make_response
        _, data, err = _auth_download(session_id)
        if err:
            return err
        sep = "=" * 64
        header = (
            f"MFG AGENT — SUPPLIER SOURCING REPORT\n{sep}\n"
            f"Session  : {session_id}\n"
            f"Query    : {data.get('query','')}\n"
            f"Product  : {data.get('product','')}\n"
            f"Location : {data.get('location','')}\n"
            f"Sources  : {data.get('sources_used','')}\n"
            f"Suppliers: {data.get('suppliers_found',0)}\n"
            f"{sep}\n\n"
        )
        resp = make_response(header + data.get("report_text", "No report text available."))
        resp.headers["Content-Type"]        = "text/plain; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="report_{session_id}.txt"'
        return resp

    @app.route("/api/download-json/<session_id>")
    def download_json_route(session_id: str):
        from flask import make_response
        _, data, err = _auth_download(session_id)
        if err:
            return err
        resp = make_response(json.dumps(data, indent=2, ensure_ascii=False))
        resp.headers["Content-Type"]        = "application/json; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="report_{session_id}.json"'
        return resp

    # ── Health / Stats ────────────────────────────────────────────────────────

    @app.route("/api/health")
    def health():
        sc = orchestrator.scraper_cfg
        return jsonify({
            "status":       "ok",
            "model":        cfg.GROQ_MODEL,
            "tavily":       sc.has_tavily,
            "serper":       sc.has_serper,
            "ddg_fallback": True,
            "firebase":     bool(cfg.FIREBASE_PROJECT_ID),
            "chroma":       cfg.CHROMA_PERSIST_DIR or cfg.CHROMA_HOST,
        })

    @app.route("/api/stats")
    @require_auth
    def stats_endpoint(user: dict):
        try:
            stats = get_store().get_stats()
        except Exception as e:
            stats = {"error": str(e)}
        return jsonify(stats)

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

app = create_app()
