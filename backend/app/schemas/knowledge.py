"""Schemas for the public knowledge-search API."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class KnowledgeQuery(BaseModel):
    keyword: str = Field(..., min_length=1)
    version: Optional[str] = None
    product: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=100)


class KnowledgeResult(BaseModel):
    chunk_id: str
    content: str
    section: Optional[str] = None
    heading_path: Optional[Any] = None
    document_id: str
    doc_name: str
    product: Optional[str] = None
    version: Optional[str] = None
    version_status: str
    source_pages: List[int] = Field(default_factory=list)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    images: List[Any] = Field(default_factory=list)
    applicable_versions: List[str] = Field(default_factory=list)
    score: float
