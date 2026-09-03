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
from app.services.qa.question_service import answer_question
from app.services.conversation_service import ConversationNotFoundError, ConversationService
from app.services.user_service import UserNotFoundError
from app.api.user import get_current_user
from app.models import User


router = APIRouter(prefix="/chat", tags=["chat"])
conversation_router = APIRouter(tags=["conversations"])
ai_client = AIClient()
logger = logging.getLogger(__name__)


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    """Build the service for one request; the API layer never executes SQL."""
    return ConversationService(ConversationRepository(db), UserRepository(db))


def require_user(requested_user_id: str, current_user: User) -> None:
    if requested_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问其他用户的数据")


def require_conversation_owner(
    conversation_id: str, current_user: User, service: ConversationService
):
    conversation = service.get_conversation(conversation_id)
    if conversation.user_id != current_user.id:
        raise ConversationNotFoundError(f"会话不存在: {conversation_id}")
    return conversation


@conversation_router.post("/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        require_user(payload.user_id, current_user)
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
    current_user: User = Depends(get_current_user),
) -> list[ConversationRead]:
    try:
        require_user(user_id, current_user)
        return service.list_user_conversations(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@conversation_router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        return require_conversation_owner(conversation_id, current_user, service)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@conversation_router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        require_conversation_owner(conversation_id, current_user, service)
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
    current_user: User = Depends(get_current_user),
) -> Response:
    try:
        require_conversation_owner(conversation_id, current_user, service)
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
    current_user: User = Depends(get_current_user),
) -> MessageRead:
    try:
        require_conversation_owner(conversation_id, current_user, service)
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
    current_user: User = Depends(get_current_user),
) -> list[MessageRead]:
    try:
        require_conversation_owner(conversation_id, current_user, service)
        return service.get_conversation_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """Persist both sides of a chat turn and return the stable API envelope."""
    try:
        require_user(request.user_id, current_user)
        if request.conversation_id:
            conversation = require_conversation_owner(
                request.conversation_id, current_user, conversation_service
            )
            conversation_id = conversation.id
        else:
            conversation = conversation_service.create_conversation(
                request.user_id,
                request.version,
            )
            conversation_id = conversation.id

        result = await answer_question(
            original_query=request.question,
            version=request.version,
            conversation_id=conversation.dify_conversation_id,
            user_id=request.user_id,
        )
        dify_conversation_id = result.get("dify_conversation_id")
        if dify_conversation_id and dify_conversation_id != conversation.dify_conversation_id:
            conversation_service.save_dify_conversation_id(
                conversation_id, dify_conversation_id
            )
        conversation_service.save_user_message(conversation_id, request.question)
        conversation_service.save_ai_message(
            conversation_id,
            result["answer"],
            answer_status=result["answer_status"],
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
        answer_status=result.get("answer_status"),
        original_query=result.get("original_query"),
        rag_query=result.get("rag_query"),
        confidence_score=result.get("confidence_score"),
        confidence_level=result.get("confidence_level"),
        confidence_reasons=result.get("confidence_reasons", []),
        requested_version=result.get("requested_version"),
        detected_version=result.get("detected_version"),
        effective_version=result.get("effective_version"),
        version_status=result.get("version_status"),
        evidence=result.get("evidence", []),
    )
    return ChatResponse(code=0, message="success", data=data)
