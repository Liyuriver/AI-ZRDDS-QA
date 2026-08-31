"""Stable schemas for keyword retrieval responses."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    chunk_id: str
    score: float
    content: str
    section: Optional[str] = None
    heading_path: Optional[Any] = None
    document_id: str
    source_file: str
    product: Optional[str] = None
    version: Optional[str] = None
    doc_type: Optional[str] = None
    applicable_versions: List[str] = Field(default_factory=list)
    page: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_pages: List[int] = Field(default_factory=list)
    images: List[Any] = Field(default_factory=list)
    version_status: Optional[str] = None


class SkippedDocument(BaseModel):
    document_id: str
    source_file: str
    status: str
    reason: str


class RetrievalResponse(BaseModel):
    query: str
    top_k: int
    indexed_documents: List[str] = Field(default_factory=list)
    skipped_documents: List[SkippedDocument] = Field(default_factory=list)
    total_candidates: int = 0
    results: List[RetrievalResult] = Field(default_factory=list)

