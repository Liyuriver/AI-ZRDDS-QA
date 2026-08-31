"""Business service for the Knowledge search endpoint."""

from typing import List

from app.schemas.knowledge import KnowledgeQuery, KnowledgeResult
from app.services.retrieval.retrieval_service import retrieve


class KnowledgeService:
    @staticmethod
    def search(query: KnowledgeQuery) -> List[KnowledgeResult]:
        """Search indexed hybrid chunks and expose the stable Knowledge shape."""
        response = retrieve(
            query=query.keyword,
            top_k=query.top_k,
            product=query.product,
            requested_version=query.version,
        )

        return [
            KnowledgeResult(
                chunk_id=result.chunk_id,
                content=result.content,
                doc_name=result.source_file,
                version=result.version or "",
                score=result.score,
            )
            for result in response.results
        ]
