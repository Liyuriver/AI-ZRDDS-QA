import asyncio

import httpx
import pytest

from app.services.ai_client import AIClient, AIServiceError, build_dify_query


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.payloads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs.get("json"))
        return next(self.responses)


def response(status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "http://dify.test/v1/chat-messages")
    return httpx.Response(status_code, request=request, json=payload)


def test_query_retries_one_transient_dify_400(monkeypatch):
    fake = FakeAsyncClient(
        [
            response(400, {"code": "temporary_failure"}),
            response(
                200,
                {
                    "answer": "已恢复",
                    "metadata": {},
                    "conversation_id": "dify-conversation-1",
                },
            ),
        ]
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setattr("app.services.ai_client.asyncio.sleep", lambda _delay: _noop())

    client = AIClient()
    client.base_url = "http://dify.test/v1"
    client.api_key = "test-key"
    result = asyncio.run(
        client.query(
            "测试问题",
            conversation_id="existing-dify-conversation",
            user_id="test-user",
        )
    )

    assert fake.calls == 2
    assert fake.payloads[0]["conversation_id"] == "existing-dify-conversation"
    assert result["answer"] == "已恢复"
    assert result["dify_conversation_id"] == "dify-conversation-1"


def test_query_returns_stable_error_after_retry(monkeypatch):
    fake = FakeAsyncClient(
        [
            response(400, {"code": "bad_request"}),
            response(400, {"code": "bad_request"}),
        ]
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setattr("app.services.ai_client.asyncio.sleep", lambda _delay: _noop())

    client = AIClient()
    client.base_url = "http://dify.test/v1"
    client.api_key = "test-key"

    with pytest.raises(AIServiceError, match="Dify 暂时无法完成回答"):
        asyncio.run(client.query("测试问题", user_id="test-user"))


def test_query_turns_empty_answer_into_insufficient_evidence(monkeypatch):
    fake = FakeAsyncClient([response(200, {"answer": "   ", "metadata": {}})])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake)
    client = AIClient()
    client.base_url = "http://dify.test/v1"
    client.api_key = "test-key"

    result = asyncio.run(client.query("测试问题", user_id="test-user"))

    assert result["status"] == "insufficient_evidence"
    assert result["answer"]


def test_build_dify_query_preserves_identifiers_and_respects_limit():
    original = (
        "In DDS, what is the semantic difference between DataReader::read() and "
        "DataReader::take()? How do READ_SAMPLE_STATE and NOT_READ_SAMPLE_STATE "
        "affect whether the same sample can be returned again?"
    )
    rewritten = f"{original} " + " ".join(["read", "take"] * 20)
    query = build_dify_query(original, rewritten)
    assert len(query) <= 250
    for term in ("read", "take", "READ_SAMPLE_STATE", "NOT_READ_SAMPLE_STATE"):
        assert term.casefold() in query.casefold()
    assert query == original


def test_retrieve_knowledge_sends_bounded_query_and_records_success(monkeypatch):
    fake = FakeAsyncClient([response(200, {"records": [{
        "score": 0.9,
        "segment": {
            "id": "segment-1",
            "document_name": "formal-15-04-10.pdf",
            "segment_name": "2.2.2.5.1 Access to the data",
            "content": "read and take semantics",
        },
    }]})])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setenv("DIFY_DATASET_ID", "dataset-test")
    monkeypatch.setenv("DIFY_KB_API_KEY", "kb-test")
    client = AIClient()
    client.base_url = "http://dify.test/v1"
    original = "In DDS, what is the semantic difference between DataReader::read() and DataReader::take()? How do READ_SAMPLE_STATE and NOT_READ_SAMPLE_STATE affect whether the same sample can be returned again?"

    result = asyncio.run(client.retrieve_knowledge(original, original_query=original))

    assert result[0]["source_file"] == "formal-15-04-10.pdf"
    sent_query = fake.payloads[0]["query"]
    assert len(sent_query) <= 250
    assert client.last_retrieval_trace["status"] == "success"
    assert client.last_retrieval_trace["http_status"] == 200
    assert client.last_retrieval_trace["result_count"] == 1


def test_retrieve_knowledge_exposes_http_failure_in_trace(monkeypatch, caplog):
    fake = FakeAsyncClient([response(400, {"code": "invalid_param"})])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setenv("DIFY_DATASET_ID", "dataset-test")
    monkeypatch.setenv("DIFY_KB_API_KEY", "kb-test")
    client = AIClient()
    client.base_url = "http://dify.test/v1"

    result = asyncio.run(client.retrieve_knowledge("long query", original_query="long query"))

    assert result == []
    assert client.last_retrieval_trace["status"] == "failed"
    assert client.last_retrieval_trace["http_status"] == 400
    assert client.last_retrieval_trace["error_type"] == "invalid_param"
    assert "DIFY_RETRIEVAL_FAILED" in caplog.text
@pytest.mark.parametrize("resource", [
    {"content": "x", "metadata": {"version": "V2.0"}},
    {"content": "x", "document_metadata": {"version": "V2.0"}},
    {"content": "x", "segment": {"metadata": {"version": "V2.0"}}},
    {"content": "x", "retriever_resource": {"metadata": {"version": "V2.0"}}},
])
def test_extract_sources_preserves_nested_version_metadata(resource):
    client = AIClient()
    sources, _images = client._extract_sources({"metadata": {"retriever_resources": [resource]}})
    assert sources[0]["version"] == "V2.0"


def test_extract_sources_does_not_invent_missing_version():
    client = AIClient()
    sources, _images = client._extract_sources({"metadata": {"retriever_resources": [{"content": "x"}]}})
    assert sources[0]["version"] is None


def test_extract_sources_preserves_segment_identity():
    client = AIClient()
    sources, _images = client._extract_sources({"metadata": {"retriever_resources": [{
        "document_name": "formal-15-04-10.pdf",
        "segment_id": "segment-42",
        "content": "read and take semantics",
    }]}})
    assert sources[0]["chunk_id"] == "segment-42"
    assert sources[0]["segment_id"] == "segment-42"


def test_extract_sources_enriches_missing_version_from_backend_metadata(monkeypatch):
    metadata = type("Metadata", (), {"version": "V2.0"})()
    monkeypatch.setattr(
        "app.services.ai_client.find_document_metadata",
        lambda **_kwargs: (metadata, "source_file"),
    )
    client = AIClient()
    sources, _images = client._extract_sources({"metadata": {"retriever_resources": [{
        "content": "x", "document_name": "ZRDDS用户手册.pdf"
    }]}})
    assert sources[0]["version"] == "V2.0"


def test_extract_sources_keeps_dify_version_over_backend_metadata(monkeypatch):
    metadata = type("Metadata", (), {"version": "V2.0"})()
    monkeypatch.setattr(
        "app.services.ai_client.find_document_metadata",
        lambda **_kwargs: (metadata, "source_file"),
    )
    client = AIClient()
    sources, _images = client._extract_sources({"metadata": {"retriever_resources": [{
        "content": "x", "version": "V1.0", "document_name": "guide.pdf"
    }]}})
    assert sources[0]["version"] == "V1.0"


async def _noop():
    return None
