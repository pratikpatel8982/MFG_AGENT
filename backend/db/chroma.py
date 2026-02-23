"""
db/chroma.py — ChromaDB integration.

Auto-selects backend:
  Cloud  → set CHROMA_API_KEY + CHROMA_TENANT + CHROMA_DATABASE
            (uses chromadb-client HTTP — zero RAM, fully persistent)
  Local  → set nothing, uses CHROMA_PERSIST_DIR
            (requires full chromadb package, fine for dev)
"""
from __future__ import annotations
import hashlib
from datetime import datetime

import chromadb

from backend.config import cfg
from .models import SupplierRecord, ReportRecord

# ── Singleton client ──────────────────────────────────────────────────────────

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    print(f"[ChromaDB] Cloud — tenant={cfg.CHROMA_TENANT} db={cfg.CHROMA_DATABASE}")
    _client = chromadb.CloudClient(
        api_key=cfg.CHROMA_API_KEY,
        tenant=cfg.CHROMA_TENANT,
        database=cfg.CHROMA_DATABASE,
    )
    return _client


# ── ChromaStore ───────────────────────────────────────────────────────────────

class ChromaStore:
    SUPPLIERS_COLLECTION = "suppliers"
    REPORTS_COLLECTION   = "reports"
    HISTORY_COLLECTION   = "history"

    def __init__(self):
        client = _get_client()
        # No local embedding function — cloud handles embeddings server-side,
        # local falls back to ChromaDB's default (only loaded when needed)
        self._suppliers = client.get_or_create_collection(
            self.SUPPLIERS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._reports = client.get_or_create_collection(
            self.REPORTS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._history = client.get_or_create_collection(
            self.HISTORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Suppliers ─────────────────────────────────────────────────────────────

    def save_suppliers(self, session_id: str, user_id: str, query: str, suppliers: list[dict]):
        if not suppliers:
            return
        ids, docs, metas = [], [], []
        for s in suppliers:
            rec = SupplierRecord(
                id=f"{session_id}_{hashlib.md5(s.get('name','').encode()).hexdigest()[:8]}",
                session_id=session_id,
                user_id=user_id,
                query=query,
                name=s.get("name", "Unknown"),
                location=s.get("location", ""),
                products=s.get("products") or [],
                website=s.get("website", ""),
                contact=s.get("contact", ""),
                description=s.get("description", ""),
                certifications=s.get("certifications") or [],
                min_order=s.get("min_order", ""),
                source=s.get("source", ""),
            )
            ids.append(rec.id)
            docs.append(rec.to_document())
            metas.append(rec.to_metadata())
        self._suppliers.upsert(ids=ids, documents=docs, metadatas=metas)

    def search_suppliers(self, query_text: str, user_id: str = "", n_results: int = 20) -> list[dict]:
        where = {"user_id": user_id} if user_id else None
        try:
            count = self._suppliers.count()
            if count == 0:
                return []
            results = self._suppliers.query(
                query_texts=[query_text],
                n_results=min(n_results, count),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception as e:
            print(f"[ChromaDB] search_suppliers error: {e}")
            return []

    def get_user_suppliers(self, user_id: str, limit: int = 100, session_id: str = None) -> list[dict]:
        try:
            if session_id:
                where = {
                    "$and": [
                        {"user_id": user_id},
                        {"session_id": session_id}
                    ]
                }
            else:
                where = {"user_id": user_id}

            results = self._suppliers.get(
                where=where,
                limit=limit,
                include=["metadatas"],
            )
            return list(results["metadatas"])
        except Exception as e:
            print(f"[ChromaDB] get_user_suppliers error: {e}")
            return []

    # ── Reports ───────────────────────────────────────────────────────────────

    def save_report(self, state_dict: dict, elapsed: float = 0.0):
        rec = ReportRecord(
            id=state_dict["session_id"],
            user_id=state_dict.get("user_id", ""),
            query=state_dict.get("query", ""),
            product=state_dict.get("product", ""),
            location=state_dict.get("location", ""),
            report_text=state_dict.get("report", ""),
            suppliers_found=state_dict.get("suppliers_found", 0),
            sources_used=state_dict.get("sources_used") or [],
            elapsed_seconds=elapsed,
        )
        self._reports.upsert(
            ids=[rec.id],
            documents=[rec.to_document()],
            metadatas=[rec.to_metadata()],
        )

    def get_report(self, session_id: str) -> dict | None:
        try:
            r = self._reports.get(ids=[session_id], include=["metadatas"])
            if r["ids"]:
                meta = dict(r["metadatas"][0])
                meta["session_id"] = session_id
                return meta
        except Exception as e:
            print(f"[ChromaDB] get_report error: {e}")
        return None

    def get_user_reports(self, user_id: str, limit: int = 50) -> list[dict]:
        try:
            results = self._reports.get(
                where={"user_id": user_id},
                limit=limit,
                include=["metadatas"],
            )
            items = [
                {**meta, "session_id": sid}
                for meta, sid in zip(results["metadatas"], results["ids"])
            ]
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception as e:
            print(f"[ChromaDB] get_user_reports error: {e}")
            return []

    def delete_report(self, session_id: str):
        try:
            self._reports.delete(ids=[session_id])
        except Exception:
            pass
        try:
            results = self._suppliers.get(where={"session_id": session_id}, include=[])
            if results["ids"]:
                self._suppliers.delete(ids=results["ids"])
        except Exception:
            pass
        try:
            results = self._history.get(where={"session_id": session_id}, include=[])
            if results["ids"]:
                self._history.delete(ids=results["ids"])
        except Exception:
            pass

    def search_reports(self, query_text: str, user_id: str = "", n_results: int = 10) -> list[dict]:
        where = {"user_id": user_id} if user_id else None
        try:
            count = self._reports.count()
            if count == 0:
                return []
            results = self._reports.query(
                query_texts=[query_text],
                n_results=min(n_results, count),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception as e:
            print(f"[ChromaDB] search_reports error: {e}")
            return []

    # ── History ───────────────────────────────────────────────────────────────

    def log_query(self, user_id: str, query: str, session_id: str):
        entry_id = f"{user_id}_{session_id}"
        self._history.upsert(
            ids=[entry_id],
            documents=[query],
            metadatas=[{
                "user_id":    user_id,
                "query":      query,
                "session_id": session_id,
                "created_at": datetime.utcnow().isoformat(),
            }],
        )

    def get_user_history(self, user_id: str, limit: int = 20) -> list[dict]:
        try:
            results = self._history.get(
                where={"user_id": user_id},
                limit=limit,
                include=["metadatas"],
            )
            return sorted(results["metadatas"], key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception as e:
            print(f"[ChromaDB] get_user_history error: {e}")
            return []

    def similar_queries(self, query_text: str, user_id: str = "", n: int = 5) -> list[dict]:
        where = {"user_id": user_id} if user_id else None
        try:
            count = self._history.count()
            if count == 0:
                return []
            results = self._history.query(
                query_texts=[query_text],
                n_results=min(n, count),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception as e:
            print(f"[ChromaDB] similar_queries error: {e}")
            return []

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_suppliers": self._suppliers.count(),
            "total_reports":   self._reports.count(),
            "total_queries":   self._history.count(),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format_query_results(results: dict) -> list[dict]:
        out = []
        ids       = results.get("ids", [[]])[0]
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i, doc_id in enumerate(ids):
            entry = dict(metas[i]) if i < len(metas) else {}
            entry["_id"]       = doc_id
            entry["_document"] = docs[i] if i < len(docs) else ""
            entry["_score"]    = round(1 - (distances[i] if i < len(distances) else 1), 3)
            out.append(entry)
        return out


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: ChromaStore | None = None

def get_store() -> ChromaStore:
    global _store
    if _store is None:
        _store = ChromaStore()
    return _store