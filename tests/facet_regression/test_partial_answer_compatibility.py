from app.schemas.chat import ChatData, MessageRead


def test_partial_answer_is_schema_compatible_with_success_status():
    data = ChatData(
        conversation_id="conversation-id",
        answer="A retained, non-empty answer.",
        status="answered",
        answer_status="PARTIAL_ANSWER",
    )
    assert data.status == "answered"
    assert data.answer_status == "PARTIAL_ANSWER"


def test_persisted_partial_answer_is_readable():
    message = MessageRead.model_validate({
        "id": "message-id",
        "conversation_id": "conversation-id",
        "role": "assistant",
        "content": "A retained answer.",
        "answer_status": "PARTIAL_ANSWER",
        "created_at": "2026-09-08T00:00:00",
    })
    assert message.answer_status == "PARTIAL_ANSWER"
