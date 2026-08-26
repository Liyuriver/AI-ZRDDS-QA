"""Chat API endpoints."""

from uuid import uuid4

from fastapi import APIRouter

from app.schemas.chat import ChatData, ChatRequest, ChatResponse
from app.services.ai_client import AIClient


router = APIRouter(prefix="/chat", tags=["chat"])
ai_client = AIClient()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Answer a question through the current Mock AI client."""
    conversation_id = request.conversation_id or f"conv_{uuid4().hex}"

    result = await ai_client.query(
        question=request.question,
        version=request.version,
        conversation_id=conversation_id,
        user_id=request.user_id,
    )

    data = ChatData(
        conversation_id=conversation_id,
        answer=result["answer"],
        status=result["status"],
        sources=result.get("sources", []),
    )
    return ChatResponse(code=0, message="success", data=data)
