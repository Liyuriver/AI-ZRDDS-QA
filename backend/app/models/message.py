"""Message ORM model."""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.database.time import beijing_now


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    answer_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sources: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    images: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=beijing_now)
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
