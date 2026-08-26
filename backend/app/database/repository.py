"""Repository layer for conversation persistence."""

from typing import List, Optional
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Conversation, Message


class RepositoryError(RuntimeError):
    """A persistence operation failed."""


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_conversation(self, user_id: str, version: Optional[str] = None) -> Conversation:
        conversation = Conversation(user_id=user_id, version=version)
        try:
            self.db.add(conversation)
            self.db.commit()
            self.db.refresh(conversation)
            return conversation
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("创建会话失败") from exc

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        try:
            return self.db.get(Conversation, conversation_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("查询会话失败") from exc

    def save_message(self, conversation_id: str, role: str, content: str) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError("role 必须是 user 或 assistant")
        message = Message(conversation_id=conversation_id, role=role, content=content)
        try:
            self.db.add(message)
            self.db.commit()
            self.db.refresh(message)
            return message
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("保存消息失败") from exc

    def get_messages_by_conversation_id(self, conversation_id: str) -> List[Message]:
        try:
            return (
                self.db.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
                .all()
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("查询会话消息失败") from exc
