from app.services.retrieval.fusion_service import fuse_candidates
from app.services.retrieval import rerank_service


def candidate(chunk_id, content, source_file="guide.pdf", section="3.3.2"):
    return {"chunk_id": chunk_id, "content": content, "source_file": source_file, "section": section, "raw_score": 1}


def test_fusion_deduplicates_cross_path_and_uses_rrf():
    same = candidate("chunk-1", "Domain Topic Type QoS")
    result = fuse_candidates(
        [same, candidate("chunk-2", "unrelated")],
        [dict(same, raw_score=0.9), candidate("chunk-3", "other")],
        top_n=15,
        rrf_k=60,
    )
    assert len(result) == 3
    first = next(item for item in result if item["chunk_id"] == "chunk-1")
    assert first["retrieval_source"] == ["bm25", "dify"]
    assert first["fusion_score"] == 1 / 61 + 1 / 61


def test_fusion_matches_same_content_without_chunk_id():
    result = fuse_candidates(
        [candidate("", "same content", "a.pdf", "x")],
        [candidate("", "same   content", "b.pdf", "y")],
    )
    assert len(result) == 1
    assert set(result[0]["retrieval_source"]) == {"bm25", "dify"}


def test_rerank_fallback_when_api_key_is_missing(monkeypatch):
    monkeypatch.setattr(rerank_service, "RERANK_ENABLED", True)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(rerank_service, "DASHSCOPE_API_KEY", "")
    result = rerank_service.rerank("Domain Topic", [
        {"id": "a", "content": "Domain Topic", "fusion_score": .01},
        {"id": "b", "content": "unrelated", "fusion_score": .02},
    ], top_n=1)
    # Model-disabled mode deliberately preserves the RRF order as the safe
    # degradation specified by the retrieval contract.
    assert result[0]["id"] == "b"
    assert result[0]["rerank_rank"] == 1


def test_cloud_rerank_maps_scores_back_to_candidates(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"output": {"results": [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.2}]}}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.payload = None
            self.headers = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, *, json, headers):
            assert url.endswith("/services/rerank/text-rerank/text-rerank")
            assert headers["Authorization"] == "Bearer test-only-token"
            self.payload = json
            assert json["model"] == "qwen3.7-text-rerank"
            assert json["input"]["query"] == "Domain Topic"
            assert json["parameters"]["top_n"] == 2
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(rerank_service.httpx, "Client", lambda **kwargs: fake)
    monkeypatch.setattr(rerank_service, "DASHSCOPE_API_KEY", "test-only-token")
    monkeypatch.setattr(rerank_service, "DASHSCOPE_WORKSPACE_ID", "workspace-test")
    monkeypatch.setattr(rerank_service, "RERANK_ENABLED", True)
    result = rerank_service.rerank("Domain Topic", [
        {"id": "a", "content": "a", "fusion_score": .02},
        {"id": "b", "content": "b", "fusion_score": .01},
    ], top_n=2)
    assert [item["id"] for item in result] == ["b", "a"]
    assert result[0]["rerank_score"] == 0.91
    assert result[0]["rerank_rank"] == 1


def test_cloud_rerank_request_failure_falls_back(monkeypatch):
    class BrokenClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            raise TimeoutError("simulated timeout")

    monkeypatch.setattr(rerank_service.httpx, "Client", BrokenClient)
    monkeypatch.setattr(rerank_service, "DASHSCOPE_API_KEY", "test-only-token")
    monkeypatch.setattr(rerank_service, "DASHSCOPE_WORKSPACE_ID", "workspace-test")
    monkeypatch.setattr(rerank_service, "RERANK_ENABLED", True)
    result = rerank_service.rerank("Domain Topic", [
        {"id": "a", "content": "a", "fusion_score": .01},
        {"id": "b", "content": "b", "fusion_score": .02},
    ], top_n=1)
    assert result[0]["id"] == "b"
