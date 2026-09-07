from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.retrieval_service import retrieve_candidates


IDL_CHANGE_QUESTION = (
    "项目将IDL中的结构体 Foo 增加一个成员后重新生成代码，但只替换了Foo.h，"
    "未替换DataWriter/DataReader/TypeSupport相关生成文件。"
    "可能出现什么问题？应如何处理？"
)


def test_idl_change_expands_to_serialization_consistency_terms():
    rewritten = rewrite_query(IDL_CHANGE_QUESTION)

    assert "反序列化" in rewritten.terms
    assert "内部结构不同" in rewritten.terms
    assert "生成文件一致性" in rewritten.terms


def test_idl_change_retrieves_troubleshooting_serialization_chunk():
    rewritten = rewrite_query(IDL_CHANGE_QUESTION)

    results = retrieve_candidates(rewritten.search_query, top_k=10)

    assert any(
        item.get("source_file") == "ZRDDS故障排查指南.pdf"
        and item.get("chunk_id") == "chunk-0052"
        for item in results
    )


def test_chat_rerank_uses_rewritten_query(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.api import chat as chat_api
    from app.schemas.chat import ChatRequest

    captured = {}
    conversation = SimpleNamespace(id="conversation-id", user_id="user-id", dify_conversation_id=None)

    class FakeConversationService:
        def create_conversation(self, *_args):
            return conversation

        def save_dify_conversation_id(self, *_args):
            pass

        def save_user_message(self, *_args):
            pass

        def save_ai_message(self, *_args, **_kwargs):
            pass

    async def fake_retrieve_knowledge(*_args, **_kwargs):
        return []

    async def fake_query(**_kwargs):
        return {
            "answer": "测试回答",
            "status": "answered",
            "answer_status": "answered",
            "sources": [],
            "images": [],
        }

    def fake_rerank(query, _candidates, *, top_n):
        captured["query"] = query
        captured["top_n"] = top_n
        return []

    monkeypatch.setattr(chat_api, "retrieve_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_api.ai_client, "retrieve_knowledge", fake_retrieve_knowledge)
    monkeypatch.setattr(chat_api.ai_client, "query", fake_query)
    monkeypatch.setattr(chat_api, "rerank", fake_rerank)

    asyncio.run(
        chat_api.chat(
            ChatRequest(question=IDL_CHANGE_QUESTION, user_id="user-id"),
            FakeConversationService(),
            SimpleNamespace(id="user-id"),
        )
    )

    assert "反序列化" in captured["query"]
    assert "内部结构不同" in captured["query"]
    assert "生成文件一致性" in captured["query"]
