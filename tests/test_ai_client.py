import asyncio

import httpx
import pytest

from app.services.ai_client import AIClient, AIServiceError


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
