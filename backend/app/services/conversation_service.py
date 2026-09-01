"""Business operations for conversations, independent of the API layer."""

from typing import Any, List, Optional
from uuid import UUID

from app.database.repository import ConversationRepository
from app.models import Conversation, Message


class ConversationNotFoundError(LookupError):
    """The requested conversation does not exist."""


class ConversationService:
    def __init__(self, repository: ConversationRepository, user_repository=None):
        self.repository = repository
        self.user_repository = user_repository

    @staticmethod
    def _validate_id(conversation_id: str) -> None:
        try:
            UUID(str(conversation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("conversation_id 必须是有效 UUID") from exc

    def create_conversation(self, user_id: str, version: Optional[str] = None, title: str = "新会话") -> Conversation:
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")
        if self.user_repository is not None and self.user_repository.get(user_id) is None:
            from app.services.user_service import UserNotFoundError
            raise UserNotFoundError(f"用户不存在: {user_id}")
        return self.repository.create_conversation(user_id=user_id, title=title, version=version)

    def list_user_conversations(self, user_id: str) -> List[Conversation]:
        if self.user_repository is not None and self.user_repository.get(user_id) is None:
            from app.services.user_service import UserNotFoundError
            raise UserNotFoundError(f"用户不存在: {user_id}")
        return self.repository.list_by_user_id(user_id)

    def add_message(self, conversation_id: str, role: str, content: str) -> Message:
        return self._save_message(conversation_id, role, content)

    def get_conversation_messages(self, conversation_id: str) -> List[Message]:
        return self.get_conversation_history(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        self.repository.delete(self.get_conversation(conversation_id))

    def update_conversation_title(self, conversation_id: str, title: str) -> Conversation:
        normalized = title.strip()
        if not normalized:
            raise ValueError("会话标题不能为空")
        if len(normalized) > 255:
            raise ValueError("会话标题不能超过 255 个字符")
        return self.repository.update_title(self.get_conversation(conversation_id), normalized)

    def save_dify_conversation_id(
        self, conversation_id: str, dify_conversation_id: str
    ) -> Conversation:
        normalized = dify_conversation_id.strip()
        if not normalized:
            raise ValueError("Dify conversation_id 不能为空")
        return self.repository.update_dify_conversation_id(
            self.get_conversation(conversation_id), normalized
        )

    def save_user_message(self, conversation_id: str, content: str) -> Message:
        return self._save_message(conversation_id, "user", content)

    def save_ai_message(
        self,
        conversation_id: str,
        content: str,
        *,
        answer_status: str = "answered",
        sources: Optional[list[dict[str, Any]]] = None,
        images: Optional[list[dict[str, Any]]] = None,
    ) -> Message:
        return self._save_message(
            conversation_id,
            "assistant",
            content,
            answer_status=answer_status,
            sources=sources,
            images=images,
        )

    def get_conversation(self, conversation_id: str) -> Conversation:
        """Return a conversation or raise a domain-level not-found error."""
        self._validate_id(conversation_id)
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(f"会话不存在: {conversation_id}")
        return conversation

    def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        answer_status: Optional[str] = None,
        sources: Optional[list[dict[str, Any]]] = None,
        images: Optional[list[dict[str, Any]]] = None,
    ) -> Message:
        self._validate_id(conversation_id)
        if not content or not content.strip():
            raise ValueError("消息内容不能为空")
        self.get_conversation(conversation_id)
        return self.repository.save_message(
            conversation_id,
            role,
            content,
            answer_status=answer_status,
            sources=sources,
            images=images,
        )

    def get_conversation_history(self, conversation_id: str) -> List[Message]:
        self._validate_id(conversation_id)
        self.get_conversation(conversation_id)
        return self.repository.get_messages_by_conversation_id(conversation_id)
