from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.retrieval_service import RetrievalService


QUESTION = "订阅端反复读取到同一批样本，开发者怀疑读取接口选择不当。应如何从 read/take 语义与样本状态角度定位？"


def test_read_take_rewrite_preserves_state_identifiers():
    rewritten = rewrite_query(QUESTION)
    text = rewritten.search_query
    for term in ("read", "take", "SampleStateKind", "READ_SAMPLE_STATE", "NOT_READ_SAMPLE_STATE", "sample_state"):
        assert term in text


def test_read_take_semantics_are_retrievable_from_registered_formal_document():
    service = RetrievalService()
    # The golden case must exercise the raw user question; rewrite is part of
    # the retrieval implementation, not hand-fed test input.
    results = service.retrieve(QUESTION, top_k=50).results
    content = "\n".join(item.content for item in results)
    assert "general semantics of the" in content
    assert "data remains the middleware" in content
    assert "no longer be accessible to the DataReader" in content
