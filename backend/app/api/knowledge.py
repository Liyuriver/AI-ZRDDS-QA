from fastapi import APIRouter, HTTPException
from app.schemas.knowledge import KnowledgeQuery, KnowledgeResult
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

@router.post("/search", response_model=list[KnowledgeResult])
def search_knowledge(query: KnowledgeQuery) -> list[KnowledgeResult]:
    try:
        results = KnowledgeService.search(query)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
