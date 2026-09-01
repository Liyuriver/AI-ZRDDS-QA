"""Business service for the Knowledge search endpoint."""

from typing import List

from app.schemas.knowledge import KnowledgeQuery, KnowledgeResult
from app.services.retrieval.retrieval_service import retrieve


class KnowledgeService:
    @staticmethod
    def search(query: KnowledgeQuery) -> List[KnowledgeResult]:
        """Search indexed hybrid chunks and expose the stable Knowledge shape."""
        requested_version = (query.version or "").strip() or None
        product = (query.product or "").strip() or None
        response = retrieve(
            query=query.keyword,
            top_k=query.top_k,
            product=product,
            requested_version=requested_version,
        )

        return [
            KnowledgeResult(
                chunk_id=result.chunk_id,
                content=result.content,
                section=result.section,
                heading_path=result.heading_path,
                document_id=result.document_id,
                doc_name=result.source_file,
                product=result.product,
                version=result.version,
                version_status=result.version_status or "unknown",
                source_pages=result.source_pages,
                page_start=result.page_start,
                page_end=result.page_end,
                images=result.images,
                applicable_versions=result.applicable_versions,
                score=result.score,
            )
            for result in response.results
        ]
