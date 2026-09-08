from app.services.retrieval.fusion_service import fuse_candidates


def test_fusion_deduplicates_by_chunk_and_combines_sources():
    result = fuse_candidates(
        [{"chunk_id": "c1", "source_file": "a.pdf", "section": "1", "content": "Domain Topic QoS", "score": 9}],
        [{"chunk_id": "c1", "source_file": "a.pdf", "section": "1", "content": "Domain Topic QoS", "score": 0.2}],
        top_n=15,
    )
    assert len(result) == 1
    assert result[0]["retrieval_source"] == ["bm25", "dify"]
    assert result[0]["fusion_score"] == 1 / 61 + 1 / 61


def test_fusion_keeps_bm25_only_evidence():
    result = fuse_candidates(
        [{"chunk_id": "c1", "source_file": "故障排查.pdf", "section": "3.3.2", "content": "Domain Topic Type QoS", "score": 3}],
        [],
    )
    assert result[0]["content"] == "Domain Topic Type QoS"
    assert result[0]["retrieval_source"] == ["bm25"]


def test_fusion_preserves_dify_segment_identity():
    result = fuse_candidates(
        [],
        [{
            "segment_id": "segment-42",
            "chunk_id": "segment-42",
            "source_file": "formal-15-04-10.pdf",
            "section": "2.2.2.5.1 Access to the data",
            "content": "read and take semantics",
            "score": 0.9,
        }],
    )
    assert result[0]["chunk_id"] == "segment-42"
    assert result[0]["segment_id"] == "segment-42"
