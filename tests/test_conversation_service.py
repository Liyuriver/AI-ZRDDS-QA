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
        question = service.save_user_message(conversation.id, "ZRDDS 在 Linux 下最低版本要求是什么？")
        answer = service.save_ai_message(conversation.id, "这是测试回答。")
        history = service.get_conversation_history(conversation.id)

        assert [item.role for item in history] == ["user", "assistant"]
        assert [item.content for item in history] == ["ZRDDS 在 Linux 下最低版本要求是什么？", "这是测试回答。"]
        assert all(item.conversation_id == conversation.id for item in history)
        assert question.id != answer.id

    with Session() as db:
        assert db.get(Conversation, conversation.id) is not None
        assert db.query(Message).filter(Message.conversation_id == conversation.id).count() == 2


def test_application_time_is_beijing_local_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    expected = datetime.now(ZoneInfo("Asia/Shanghai"))
    actual = beijing_now()
    assert actual.tzinfo is None
    assert abs((actual - expected.replace(tzinfo=None)).total_seconds()) < 2
