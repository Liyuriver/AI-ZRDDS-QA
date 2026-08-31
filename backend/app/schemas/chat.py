"""Pydantic schemas used by the chat API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field
from datetime import datetime


ChatStatus = Literal["answered", "insufficient_evidence", "error"]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User's question")
    version: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: str = Field(..., min_length=1)


class Source(BaseModel):
    document: str
    section: Optional[str] = None
    page: Optional[int] = None
    score: Optional[float] = None
    quote: str


class ChatData(BaseModel):
    conversation_id: str
    answer: str
    status: ChatStatus
    sources: list[Source] = Field(default_factory=list)


class ChatResponse(BaseModel):
    code: int
    message: str
    data: Optional[ChatData] = None


class ConversationCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: str = Field(default="新会话", min_length=1, max_length=255)
    version: Optional[str] = None


class ConversationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    title: str
    version: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class MessageRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
