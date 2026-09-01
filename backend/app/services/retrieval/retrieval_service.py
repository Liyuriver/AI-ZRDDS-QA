"""Metadata-aware BM25 retrieval, independent from preprocessing and API routes."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.schemas.metadata import DocumentMetadata
from app.schemas.retrieval import RetrievalResponse, RetrievalResult, SkippedDocument
from app.services.metadata.metadata_service import (
    list_documents as list_metadata,
    merge_metadata_into_chunks,
)
from app.services.metadata.version_service import UNKNOWN, version_status

from app.services.retrieval.bm25 import BM25Index

logger = logging.getLogger(__name__)
HYBRID_PATH = Path(__file__).resolve().parents[3] / "data" / "hybrid"


class RetrievalService:
    def __init__(self, hybrid_path: Optional[Path] = None) -> None:
        self.hybrid_path = Path(hybrid_path) if hybrid_path else HYBRID_PATH
        self.index = BM25Index()
        self.indexed_documents: List[str] = []
        self.skipped_documents: List[SkippedDocument] = []
        self._chunks: List[Dict[str, Any]] = []

    def _available_chunks(self, metadata: DocumentMetadata) -> Optional[List[Mapping[str, Any]]]:
        """Find chunks by manifest source_file, not by a document-specific filename rule."""
        candidates = []
        for path in self.hybrid_path.rglob("chunks.json") if self.hybrid_path.exists() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, list) or not payload:
                    continue
                matching = [chunk for chunk in payload if chunk.get("document") == metadata.source_file
                            or chunk.get("source_file") == metadata.source_file]
                if matching:
                    candidates.extend(matching)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable chunks file %s: %s", path, exc)
        return candidates or None

    def load_documents(self) -> Tuple[List[Dict[str, Any]], List[SkippedDocument]]:
        chunks: List[Dict[str, Any]] = []
        skipped: List[SkippedDocument] = []
        for metadata in list_metadata():
            available = self._available_chunks(metadata)
            if not available:
                skipped.append(SkippedDocument(
                    document_id=metadata.document_id,
                    source_file=metadata.source_file,
                    status="pending_hybrid",
                    reason="chunks_not_available",
                ))
                logger.info("skipped: %s (pending_hybrid)", metadata.source_file)
                continue
            chunks.extend(merge_metadata_into_chunks(available, metadata))
        return chunks, skipped

    def build_index(self) -> RetrievalResponse:
        self._chunks, skipped = self.load_documents()
        self.skipped_documents = skipped
        self.indexed_documents = sorted({chunk["document_id"] for chunk in self._chunks})
        self.index.build_index(self._chunks)
        return RetrievalResponse(
            query="", top_k=0, indexed_documents=self.indexed_documents,
            skipped_documents=skipped, total_candidates=len(self._chunks), results=[]
        )

    def retrieve(self, query: str, top_k: int = 5, document_id: Optional[str] = None,
                 product: Optional[str] = None, doc_type: Optional[str] = None,
                 requested_version: Optional[str] = None) -> RetrievalResponse:
        if not self._chunks:
            self.build_index()
        candidates = [chunk for chunk in self._chunks
                      if (document_id is None or chunk["document_id"] == document_id)
                      and (product is None or chunk.get("product") == product)
                      and (doc_type is None or chunk.get("doc_type") == doc_type)
                      and (requested_version is None or
                           version_status(chunk, requested_version) == "compatible")]
        ranked = BM25Index().build_index(candidates).search(query, top_k) if candidates else []
        results = []
        for item in ranked:
            item["version_status"] = (version_status(item, requested_version)
                                       if requested_version is not None else UNKNOWN)
            results.append(RetrievalResult(**item))
        return RetrievalResponse(
            query=query, top_k=top_k, indexed_documents=self.indexed_documents,
            skipped_documents=self.skipped_documents, total_candidates=len(candidates), results=results
        )


_default_service = RetrievalService()


def load_documents() -> Tuple[List[Dict[str, Any]], List[SkippedDocument]]:
    return _default_service.load_documents()


def build_index() -> RetrievalResponse:
    return _default_service.build_index()


def retrieve(query: str, top_k: int = 5, document_id: Optional[str] = None,
             product: Optional[str] = None, doc_type: Optional[str] = None,
             requested_version: Optional[str] = None) -> RetrievalResponse:
    return _default_service.retrieve(query, top_k, document_id, product, doc_type, requested_version)

