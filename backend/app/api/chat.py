"""Chat API endpoints."""

import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import ConversationRepository, RepositoryError, UserRepository
from app.schemas.chat import (
    ChatData,
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
)
from app.services.ai_client import AIClient, AIServiceError
from app.services.conversation_service import ConversationNotFoundError, ConversationService
from app.services.user_service import UserNotFoundError
from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.retrieval_service import retrieve_candidates
from app.services.retrieval.fusion_service import fuse_candidates
from app.services.retrieval.rerank_service import rerank
from app.config import BM25_TOP_K, DIFY_TOP_K, RERANK_TOP_N, RRF_TOP_N, RRF_K


router = APIRouter(prefix="/chat", tags=["chat"])
conversation_router = APIRouter(tags=["conversations"])
ai_client = AIClient()
logger = logging.getLogger(__name__)


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    """Build the service for one request; the API layer never executes SQL."""
    return ConversationService(ConversationRepository(db), UserRepository(db))


@conversation_router.post("/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    try:
        return service.create_conversation(payload.user_id, payload.version, payload.title)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        logger.exception(
            "Create conversation API failed: user_id=%s title=%s",
            payload.user_id,
            payload.title,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "创建会话时发生数据库错误",
                "error_type": type(exc.__cause__ or exc).__name__,
            },
        ) from exc


@conversation_router.get("/users/{user_id}/conversations", response_model=list[ConversationRead])
def list_conversations(
    user_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationRead]:
    try:
        return service.list_user_conversations(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@conversation_router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    try:
        return service.get_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@conversation_router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    try:
        return service.update_conversation_title(conversation_id, payload.title)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="会话标题暂时无法保存") from exc


@conversation_router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> Response:
    try:
        service.delete_conversation(conversation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="会话暂时无法删除") from exc


@conversation_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=201,
)
def add_message(
    conversation_id: str,
    payload: MessageCreate,
    service: ConversationService = Depends(get_conversation_service),
) -> MessageRead:
    try:
        return service.add_message(conversation_id, payload.role, payload.content)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@conversation_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
)
def get_messages(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> list[MessageRead]:
    try:
        return service.get_conversation_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    """Persist both sides of a chat turn and return the stable API envelope."""
    try:
        if request.conversation_id:
            conversation = conversation_service.get_conversation(request.conversation_id)
            if conversation.user_id != request.user_id:
                raise ConversationNotFoundError(f"会话不存在: {request.conversation_id}")
            conversation_id = conversation.id
        else:
            conversation = conversation_service.create_conversation(
                request.user_id,
                request.version,
            )
            conversation_id = conversation.id

        rewritten = rewrite_query(request.question)
        bm25_results = retrieve_candidates(rewritten.search_query, top_k=BM25_TOP_K)
        dify_results = await ai_client.retrieve_knowledge(rewritten.search_query, top_k=DIFY_TOP_K)
        fused = fuse_candidates(bm25_results, dify_results, top_n=RRF_TOP_N, rrf_k=RRF_K)
        evidence = rerank(request.question, fused, top_n=RERANK_TOP_N)
        logger.debug("original_query=%r rewritten_query=%r rewrite_terms=%s", request.question, rewritten.search_query, rewritten.terms)
        logger.debug("BM25 Top10=%s", [(x.get("chunk_id"), x.get("source_file"), x.get("rank"), x.get("raw_score")) for x in bm25_results])
        logger.debug("Dify Top10=%s", [(x.get("chunk_id"), x.get("source_file"), x.get("rank"), x.get("raw_score")) for x in dify_results])
        logger.debug("RRF Top15=%s", [(x.get("chunk_id"), x.get("source_file"), x.get("fusion_score")) for x in fused])
        logger.debug("Rerank Top5=%s", [(x.get("chunk_id"), x.get("source_file"), x.get("rerank_score"), x.get("rerank_rank")) for x in evidence])
        external_context = "\n\n".join(
            f"[证据{index}]\n来源：{item.get('source_file', '')}\n章节：{item.get('section', '')}\n内容：{item.get('content', '')}"
            for index, item in enumerate(evidence, 1)
        )
        result = await ai_client.query(
            question=request.question,
            version=request.version,
            conversation_id=conversation.dify_conversation_id,
            user_id=request.user_id,
            external_context=external_context,
            evidence=evidence,
        )
        result["sources"] = [
            {"document": item.get("source_file", ""), "section": item.get("section", ""),
             "page": item.get("page", 0), "score": item.get("rerank_score", 0),
             "quote": item.get("content", "")}
            for item in evidence
        ]
        dify_conversation_id = result.get("dify_conversation_id")
        if dify_conversation_id and dify_conversation_id != conversation.dify_conversation_id:
            conversation_service.save_dify_conversation_id(
                conversation_id, dify_conversation_id
            )
        conversation_service.save_user_message(conversation_id, request.question)
        conversation_service.save_ai_message(
            conversation_id,
            result["answer"],
            answer_status=result["status"],
            sources=result.get("sources", []),
            images=result.get("images", []),
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"数据库暂时不可用: {exc}",
        ) from exc
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    data = ChatData(
        conversation_id=conversation_id,
        answer=result["answer"],
        status=result["status"],
        sources=result.get("sources", []),
        images=result.get("images", []),
    )
    return ChatResponse(code=0, message="success", data=data)
