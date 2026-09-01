from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.database.repository import ConversationRepository, UserRepository
from app.database.repository import RepositoryError
from app.schemas.chat import ConversationCreate, ConversationUpdate
from app.api.chat import create_conversation, delete_conversation, update_conversation
from app.services.conversation_service import ConversationService
from app.services.user_service import UserNotFoundError, UserService


def make_services():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    users = UserService(UserRepository(db))
    conversations = ConversationService(ConversationRepository(db), UserRepository(db))
    return db, users, conversations


def test_conversation_messages_and_user_isolation():
    db, users, conversations = make_services()
    try:
        first = users.create_user("first", "first@example.com")
        second = users.create_user("second", "second@example.com")
        one = conversations.create_conversation(first.id, title="第一会话")
        two = conversations.create_conversation(first.id, title="第二会话")
        other = conversations.create_conversation(second.id)
        assert len(conversations.list_user_conversations(first.id)) == 2
        try:
            conversations.create_conversation("missing")
            assert False
        except UserNotFoundError:
            pass

        conversations.add_message(one.id, "user", "问题")
        conversations.add_message(one.id, "assistant", "回答")
        assert [m.role for m in conversations.get_conversation_messages(one.id)] == ["user", "assistant"]
        assert conversations.get_conversation_messages(two.id) == []
        assert conversations.list_user_conversations(second.id)[0].id == other.id
    finally:
        db.close()


def test_repository_rolls_back_and_preserves_database_cause():
    db = Mock()
    db.commit.side_effect = OperationalError("INSERT", {}, RuntimeError("missing title"))
    repository = ConversationRepository(db)

    try:
        repository.create_conversation("user-id", title="test")
        assert False
    except RepositoryError as exc:
        assert isinstance(exc.__cause__, OperationalError)
    db.rollback.assert_called_once()


def test_update_conversation_api_returns_updated_title():
    service = Mock()
    service.update_conversation_title.return_value = Mock(title="新标题")

    result = update_conversation(
        "9c47ce4a-53e8-4b74-8c2a-b96b459f25ae",
        ConversationUpdate(title="新标题"),
        service,
    )

    assert result.title == "新标题"
    service.update_conversation_title.assert_called_once_with(
        "9c47ce4a-53e8-4b74-8c2a-b96b459f25ae", "新标题"
    )


def test_delete_conversation_api_returns_no_content():
    service = Mock()
    conversation_id = "9c47ce4a-53e8-4b74-8c2a-b96b459f25ae"

    response = delete_conversation(conversation_id, service)

    assert response.status_code == 204
    service.delete_conversation.assert_called_once_with(conversation_id)


def test_create_conversation_api_returns_diagnostic_database_error():
    service = Mock()
    cause = OperationalError("INSERT", {}, RuntimeError("database failure"))
    service.create_conversation.side_effect = RepositoryError("创建会话时数据库操作失败")
    service.create_conversation.side_effect.__cause__ = cause

    try:
        create_conversation(ConversationCreate(user_id="user-id", title="test"), service)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail["message"] == "创建会话时发生数据库错误"
        assert exc.detail["error_type"] == "OperationalError"
