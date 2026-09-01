from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.database.repository import ConversationRepository
from app.database.time import beijing_now
from app.models import Conversation, Message
from app.services.conversation_service import ConversationService


def test_conversation_lifecycle_persists_and_preserves_order():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        service = ConversationService(ConversationRepository(db))
        conversation = service.create_conversation("test-user")
        UUID(conversation.id)
        updated = service.update_conversation_title(conversation.id, "  Linux 版本要求  ")
        assert updated.title == "Linux 版本要求"
        mapped = service.save_dify_conversation_id(conversation.id, "dify-conversation-1")
        assert mapped.dify_conversation_id == "dify-conversation-1"
        question = service.save_user_message(conversation.id, "ZRDDS 在 Linux 下最低版本要求是什么？")
        answer = service.save_ai_message(
            conversation.id,
            "这是测试回答。",
            answer_status="answered",
            sources=[{"document": "指南.pdf", "quote": "测试证据"}],
            images=[{"url": "http://example.test/image.png"}],
        )
        history = service.get_conversation_history(conversation.id)

        assert [item.role for item in history] == ["user", "assistant"]
        assert [item.content for item in history] == ["ZRDDS 在 Linux 下最低版本要求是什么？", "这是测试回答。"]
        assert all(item.conversation_id == conversation.id for item in history)
        assert question.id != answer.id
        assert answer.answer_status == "answered"
        assert answer.sources == [{"document": "指南.pdf", "quote": "测试证据"}]
        assert answer.images == [{"url": "http://example.test/image.png"}]

    with Session() as db:
        assert db.get(Conversation, conversation.id) is not None
        assert db.query(Message).filter(Message.conversation_id == conversation.id).count() == 2

        service = ConversationService(ConversationRepository(db))
        service.delete_conversation(conversation.id)
        assert db.get(Conversation, conversation.id) is None
        assert db.query(Message).filter(Message.conversation_id == conversation.id).count() == 0


def test_application_time_is_beijing_local_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    expected = datetime.now(ZoneInfo("Asia/Shanghai"))
    actual = beijing_now()
    assert actual.tzinfo is None
    assert abs((actual - expected.replace(tzinfo=None)).total_seconds()) < 2
