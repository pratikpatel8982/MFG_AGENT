"""
db/models.py — Data models stored in ChromaDB.
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SupplierRecord:
    """A single supplier entry stored in ChromaDB."""
    id: str
    session_id: str
    user_id: str
    query: str
    name: str
    location: str = ""
    products: list[str] = field(default_factory=list)
    website: str = ""
    contact: str = ""
    description: str = ""
    certifications: list[str] = field(default_factory=list)
    min_order: str = ""
    source: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_metadata(self) -> dict:
        return {
            "session_id":     self.session_id,
            "user_id":        self.user_id,
            "query":          self.query,
            "name":           self.name,
            "location":       self.location,
            "products":       ", ".join(self.products),
            "website":        self.website,
            "contact":        self.contact or "",
            "certifications": ", ".join(self.certifications),
            "min_order":      self.min_order or "",
            "source":         self.source or "",
            "created_at":     self.created_at,
        }

    def to_document(self) -> str:
        return (
            f"{self.name}. {self.description}. "
            f"Products: {', '.join(self.products)}. "
            f"Location: {self.location}. "
            f"Certifications: {', '.join(self.certifications)}."
        )


@dataclass
class ReportRecord:
    """A full pipeline report stored in ChromaDB."""
    id: str                 # == session_id
    user_id: str
    query: str
    product: str
    location: str
    report_text: str        # full markdown report — stored in metadata
    suppliers_found: int
    sources_used: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_metadata(self) -> dict:
        return {
            "user_id":         self.user_id,
            "query":           self.query,
            "product":         self.product,
            "location":        self.location,
            "report_text":     self.report_text,   # full text here
            "suppliers_found": self.suppliers_found,
            "sources_used":    ", ".join(self.sources_used),
            "elapsed_seconds": self.elapsed_seconds,
            "created_at":      self.created_at,
        }

    def to_document(self) -> str:
        """Short text used only for semantic embedding — not for retrieval."""
        return f"{self.query}. {self.product} in {self.location}. {self.report_text[:500]}"
