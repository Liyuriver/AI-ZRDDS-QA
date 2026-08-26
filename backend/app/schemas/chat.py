"""Pydantic schemas used by the chat API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


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
