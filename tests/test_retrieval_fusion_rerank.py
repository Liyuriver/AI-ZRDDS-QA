from app.services.retrieval.fusion_service import fuse_candidates
from app.services.retrieval import rerank_service


def test_fusion_keeps_same_chunk_number_from_different_documents():
    candidates = [
        {"chunk_id": "chunk-0050", "source_file": "manual-a.pdf", "content": "alpha"},
        {"chunk_id": "chunk-0050", "source_file": "manual-b.pdf", "content": "beta"},
    ]

    fused = fuse_candidates(candidates, [], top_n=10)

    assert [(item["source_file"], item["chunk_id"]) for item in fused] == [
        ("manual-a.pdf", "chunk-0050"),
        ("manual-b.pdf", "chunk-0050"),
    ]


def test_local_fallback_promotes_configuration_match(monkeypatch):
    monkeypatch.setattr(rerank_service, "RERANK_ENABLED", False)
    candidates = [
        {
            "id": "generic",
            "chunk_id": "chunk-0057",
            "section": "异常崩溃",
            "content": "程序异常退出后的通用检查方法",
            "fusion_score": 0.032,
        },
        {
            "id": "configuration",
            "chunk_id": "chunk-0050",
            "section": "收不到数据 > ZRDDS 配置检测",
            "content": "检查域号、主题名、类型名、QoS 与地址配置是否匹配",
            "fusion_score": 0.015,
        },
    ]

    ranked = rerank_service.rerank(
        "发布端与订阅端 Topic 名称相同但收不到数据，应核对哪些匹配条件？",
        candidates,
        top_n=1,
    )

    assert ranked[0]["chunk_id"] == "chunk-0050"
