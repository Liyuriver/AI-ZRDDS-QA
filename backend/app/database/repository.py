"""Repository layer for conversation persistence."""

import logging
from typing import Any, List, Optional
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Conversation, Message, User
from app.database.time import beijing_now


logger = logging.getLogger(__name__)


class RepositoryError(RuntimeError):
    """A persistence operation failed."""


class DuplicateResourceError(RepositoryError):
    """A unique user field already exists."""


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, username: str, email: str) -> User:
        user = User(username=username, email=email)
        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            return user
        except IntegrityError as exc:
            self.db.rollback()
            raise DuplicateResourceError("username 或 email 已存在") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("创建用户失败") from exc

    def get(self, user_id: str) -> Optional[User]:
        try:
            return self.db.get(User, user_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("查询用户失败") from exc

    def get_by_username(self, username: str) -> Optional[User]:
        try:
            return self.db.query(User).filter(User.username == username).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("查询用户失败") from exc

    def list(self) -> List[User]:
        return self.db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()

    def update(self, user: User, username: Optional[str], email: Optional[str]) -> User:
        if username is not None:
            user.username = username
        if email is not None:
            user.email = email
        try:
            self.db.commit()
            self.db.refresh(user)
            return user
        except IntegrityError as exc:
            self.db.rollback()
            raise DuplicateResourceError("username 或 email 已存在") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("修改用户失败") from exc


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_conversation(self, user_id: str, title: str = "新会话", version: Optional[str] = None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title, version=version)
        try:
            self.db.add(conversation)
            self.db.commit()
            self.db.refresh(conversation)
            return conversation
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.exception("Create conversation failed: user_id=%s title=%s", user_id, title)
            raise RepositoryError("创建会话时数据库操作失败") from exc

    def list_by_user_id(self, user_id: str) -> List[Conversation]:
        return (self.db.query(Conversation).filter(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id.asc()).all())

    def delete(self, conversation: Conversation) -> None:
        try:
            self.db.delete(conversation)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("删除会话失败") from exc

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        try:
            return self.db.get(Conversation, conversation_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("查询会话失败") from exc

    def update_title(self, conversation: Conversation, title: str) -> Conversation:
        conversation.title = title
        conversation.updated_at = beijing_now()
        try:
            self.db.commit()
            self.db.refresh(conversation)
            return conversation
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("修改会话标题失败") from exc

    def update_dify_conversation_id(
        self, conversation: Conversation, dify_conversation_id: str
    ) -> Conversation:
        conversation.dify_conversation_id = dify_conversation_id
        try:
            self.db.commit()
            self.db.refresh(conversation)
            return conversation
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RepositoryError("保存 Dify 会话映射失败") from exc

    def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        answer_status: Optional[str] = None,
        sources: Optional[list[dict[str, Any]]] = None,
        images: Optional[list[dict[str, Any]]] = None,
    ) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError("role 必须是 user 或 assistant")
        next_sequence = (
            self.db.query(func.coalesce(func.max(Message.sequence_no), 0))
            .filter(Message.conversation_id == conversation_id)
            .scalar()
            + 1
        )
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence_no=next_sequence,
            answer_status=answer_status,
            sources=sources,
            images=images,
        )
        try:
            self.db.add(message)
            conversation = self.db.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = beijing_now()
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
                .order_by(
                    case((Message.sequence_no.is_(None), 0), else_=1).asc(),
                    Message.sequence_no.asc(),
                    Message.created_at.asc(),
                    case((Message.role == "user", 0), else_=1).asc(),
                    Message.id.asc(),
                )
                .all()
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("查询会话消息失败") from exc
