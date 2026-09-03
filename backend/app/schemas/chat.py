"""Pydantic schemas used by the chat API."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


ChatStatus = Literal[
    "answered", "insufficient_evidence", "error",
    "ANSWER", "VERSION_MISMATCH", "VERSION_UNCERTAIN", "LOW_CONFIDENCE", "NO_ANSWER",
]


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


class ImageSource(BaseModel):
    image_id: Optional[str] = None
    url: str
    caption: Optional[str] = None
    page: Optional[int] = None
    document: Optional[str] = None
    section: Optional[str] = None


class ChatData(BaseModel):
    conversation_id: str
    answer: str
    status: ChatStatus
    sources: list[Source] = Field(default_factory=list)
    images: list[ImageSource] = Field(default_factory=list)
    answer_status: Optional[str] = None
    original_query: Optional[str] = None
    rag_query: Optional[str] = None
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    confidence_reasons: list[str] = Field(default_factory=list)
    requested_version: Optional[str] = None
    detected_version: Optional[str] = None
    effective_version: Optional[str] = None
    version_status: Optional[str] = None
    evidence: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    code: int
    message: str
    data: Optional[ChatData] = None


class ConversationCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: str = Field(default="新会话", min_length=1, max_length=255)
    version: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


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
    answer_status: Optional[ChatStatus] = None
    sources: Optional[list[Source]] = None
    images: Optional[list[ImageSource]] = None
    created_at: datetime
