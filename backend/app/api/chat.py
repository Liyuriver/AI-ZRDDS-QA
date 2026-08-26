"""Chat API endpoints."""

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import ConversationRepository, RepositoryError
from app.schemas.chat import ChatData, ChatRequest, ChatResponse
from app.services.ai_client import AIClient
from app.services.conversation_service import ConversationNotFoundError, ConversationService


router = APIRouter(prefix="/chat", tags=["chat"])
ai_client = AIClient()


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    """Build the service for one request; the API layer never executes SQL."""
    return ConversationService(ConversationRepository(db))


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    """Persist both sides of a chat turn and return the stable API envelope."""
    try:
        if request.conversation_id:
            conversation = conversation_service.get_conversation(request.conversation_id)
            conversation_id = conversation.id
        else:
            conversation = conversation_service.create_conversation(request.user_id, request.version)
            conversation_id = conversation.id

        conversation_service.save_user_message(conversation_id, request.question)
        result = await ai_client.query(
            question=request.question,
            version=request.version,
            conversation_id=conversation_id,
            user_id=request.user_id,
        )
        conversation_service.save_ai_message(conversation_id, result["answer"])
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"数据库暂时不可用: {exc}",
        ) from exc

    data = ChatData(
        conversation_id=conversation_id,
        answer=result["answer"],
        status=result["status"],
        sources=result.get("sources", []),
    )
    return ChatResponse(code=0, message="success", data=data)
