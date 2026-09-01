"""Pydantic models for document-level knowledge-base metadata."""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata maintained independently from PDF preprocessing output."""

    document_id: str = Field(..., min_length=1)
    source_file: str = Field(..., min_length=1)
    product: Optional[str] = None
    version: Optional[str] = None
    version_raw: Optional[str] = None
    doc_type: Optional[str] = None
    publish_date: Optional[date] = None
    applicable_versions: List[str] = Field(default_factory=list)
    metadata_source: Optional[str] = None

