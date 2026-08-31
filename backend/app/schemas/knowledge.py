"""Schemas for the public knowledge-search API."""

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeQuery(BaseModel):
    keyword: str = Field(..., min_length=1)
    version: Optional[str] = None
    product: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=100)


class KnowledgeResult(BaseModel):
    chunk_id: str
    content: str
    doc_name: str
    version: str
    score: float
