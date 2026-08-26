"""Business operations for conversations, independent of the API layer."""

from typing import List, Optional
from uuid import UUID

from app.database.repository import ConversationRepository
from app.models import Conversation, Message


class ConversationNotFoundError(LookupError):
    """The requested conversation does not exist."""


class ConversationService:
    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    @staticmethod
    def _validate_id(conversation_id: str) -> None:
        try:
            UUID(str(conversation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("conversation_id 必须是有效 UUID") from exc

    def create_conversation(self, user_id: str, version: Optional[str] = None) -> Conversation:
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")
        return self.repository.create_conversation(user_id=user_id, version=version)

    def save_user_message(self, conversation_id: str, content: str) -> Message:
        return self._save_message(conversation_id, "user", content)

    def save_ai_message(self, conversation_id: str, content: str) -> Message:
        return self._save_message(conversation_id, "assistant", content)

    def _save_message(self, conversation_id: str, role: str, content: str) -> Message:
        self._validate_id(conversation_id)
        if not content or not content.strip():
            raise ValueError("消息内容不能为空")
        if self.repository.get_conversation(conversation_id) is None:
            raise ConversationNotFoundError(f"会话不存在: {conversation_id}")
        return self.repository.save_message(conversation_id, role, content)

    def get_conversation_history(self, conversation_id: str) -> List[Message]:
        self._validate_id(conversation_id)
        if self.repository.get_conversation(conversation_id) is None:
            raise ConversationNotFoundError(f"会话不存在: {conversation_id}")
        return self.repository.get_messages_by_conversation_id(conversation_id)
