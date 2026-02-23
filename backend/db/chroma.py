"""
db/chroma.py — ChromaDB integration.

Collections:
  • suppliers  — individual supplier records (semantic search by product/description)
  • reports    — full pipeline reports per session
  • history    — per-user query history

ChromaDB runs locally by default (persistent on disk).
Set CHROMA_HOST + CHROMA_API_KEY for ChromaDB Cloud.
"""
from __future__ import annotations
import hashlib
import uuid
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings

from backend.config import cfg
from .models import SupplierRecord, ReportRecord

# ── Singleton client ──────────────────────────────────────────────────────────

_client: chromadb.Client | None = None


def _get_client() -> chromadb.Client:
    global _client
    if _client is None:
        if cfg.CHROMA_HOST:
            # ChromaDB Cloud or self-hosted HTTP
            _client = chromadb.HttpClient(
                host=cfg.CHROMA_HOST,
                headers={"Authorization": f"Bearer {cfg.CHROMA_API_KEY}"}
                if cfg.CHROMA_API_KEY
                else {},
            )
        else:
            # Local persistent storage
            _client = chromadb.PersistentClient(
                path=cfg.CHROMA_PERSIST_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
    return _client


# ── ChromaStore ───────────────────────────────────────────────────────────────

class ChromaStore:
    """
    High-level ChromaDB store for the MFG Agent application.

    Collections:
      suppliers  — one doc per supplier
      reports    — one doc per pipeline run
      history    — one doc per query per user
    """

    SUPPLIERS_COLLECTION = "suppliers"
    REPORTS_COLLECTION   = "reports"
    HISTORY_COLLECTION   = "history"

    def __init__(self):
        self.client = _get_client()
        self._suppliers = self.client.get_or_create_collection(
            self.SUPPLIERS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._reports = self.client.get_or_create_collection(
            self.REPORTS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._history = self.client.get_or_create_collection(
            self.HISTORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    # ── suppliers ─────────────────────────────────────────────────────────────

    def save_suppliers(self, session_id: str, user_id: str, query: str, suppliers: list[dict]):
        """Upsert all suppliers from a pipeline run."""
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

    def search_suppliers(
        self,
        query_text: str,
        user_id: str = "",
        n_results: int = 20,
    ) -> list[dict]:
        """Semantic search over saved suppliers."""
        where = {"user_id": user_id} if user_id else None
        try:
            results = self._suppliers.query(
                query_texts=[query_text],
                n_results=min(n_results, self._suppliers.count() or 1),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception:
            return []

    def get_user_suppliers(self, user_id: str, limit: int = 100) -> list[dict]:
        """Get all suppliers for a specific user."""
        try:
            results = self._suppliers.get(
                where={"user_id": user_id},
                limit=limit,
                include=["documents", "metadatas"],
            )
            return [
                {**meta, "document": doc}
                for meta, doc in zip(results["metadatas"], results["documents"])
            ]
        except Exception:
            return []

    # ── reports ───────────────────────────────────────────────────────────────

    def save_report(self, state_dict: dict, elapsed: float = 0.0):
        """Persist a completed pipeline report."""
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
        """Retrieve a report by session_id."""
        try:
            r = self._reports.get(ids=[session_id], include=["documents", "metadatas"])
            if r["ids"]:
                meta = dict(r["metadatas"][0])
                meta["session_id"] = session_id
                return meta
        except Exception:
            pass
        return None

    def get_user_reports(self, user_id: str, limit: int = 50) -> list[dict]:
        """Get all reports for a specific user, newest first."""
        try:
            results = self._reports.get(
                where={"user_id": user_id},
                limit=limit,
                include=["documents", "metadatas"],
            )
            items = [
                {**meta, "session_id": sid}
                for meta, sid in zip(results["metadatas"], results["ids"])
            ]
            # Sort by created_at descending
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception:
            return []

    def delete_report(self, session_id: str):
        """Delete a report and its associated suppliers from ChromaDB."""
        try:
            self._reports.delete(ids=[session_id])
        except Exception:
            pass
        # Also remove suppliers from this session
        try:
            results = self._suppliers.get(
                where={"session_id": session_id}, include=[]
            )
            if results["ids"]:
                self._suppliers.delete(ids=results["ids"])
        except Exception:
            pass
        # Remove from history
        try:
            results = self._history.get(
                where={"session_id": session_id}, include=[]
            )
            if results["ids"]:
                self._history.delete(ids=results["ids"])
        except Exception:
            pass

    def search_reports(self, query_text: str, user_id: str = "", n_results: int = 10) -> list[dict]:
        """Semantic search over reports."""
        where = {"user_id": user_id} if user_id else None
        try:
            results = self._reports.query(
                query_texts=[query_text],
                n_results=min(n_results, self._reports.count() or 1),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception:
            return []

    # ── history ───────────────────────────────────────────────────────────────

    def log_query(self, user_id: str, query: str, session_id: str):
        """Log a user query to history collection."""
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
        """Get recent queries for a user, newest first."""
        try:
            results = self._history.get(
                where={"user_id": user_id},
                limit=limit,
                include=["metadatas"],
            )
            items = results["metadatas"]
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception:
            return []

    def similar_queries(self, query_text: str, user_id: str = "", n: int = 5) -> list[dict]:
        """Find semantically similar past queries."""
        where = {"user_id": user_id} if user_id else None
        try:
            results = self._history.query(
                query_texts=[query_text],
                n_results=min(n, self._history.count() or 1),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception:
            return []

    # ── stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_suppliers": self._suppliers.count(),
            "total_reports":   self._reports.count(),
            "total_queries":   self._history.count(),
        }

    # ── helpers ───────────────────────────────────────────────────────────────

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


# ── Singleton instance ────────────────────────────────────────────────────────

_store: ChromaStore | None = None


def get_store() -> ChromaStore:
    global _store
    if _store is None:
        _store = ChromaStore()
    return _store
