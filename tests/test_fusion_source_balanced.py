# -*- coding: utf-8 -*-
"""source-balanced fusion 单元测试（无网络）。"""

from app.services.retrieval.fusion_service import fuse_candidates


def _c(chunk_id, content, source_file="doc.pdf", section="1"):
    return {"chunk_id": chunk_id, "content": content, "source_file": source_file, "section": section, "raw_score": 1}


def test_trace_fields_present_on_every_candidate():
    result = fuse_candidates(
        [_c("b1", "bm25 content one")],
        [_c("d1", "dify content two")],
        top_n=None,
    )
    assert len(result) == 2
    for item in result:
        assert "source_hits" in item
        assert "bm25_rank" in item
        assert "dify_rank" in item
        assert "rrf_score" in item
        assert "candidate_reason" in item
        assert item["rrf_score"] == item["fusion_score"]


def test_multi_source_reason_and_source_hits():
    result = fuse_candidates(
        [_c("shared", "same content here")],
        [_c("shared", "same content here")],
        top_n=None,
    )
    assert len(result) == 1
    item = result[0]
    assert item["candidate_reason"] == "multi_source"
    assert set(item["source_hits"]) == {"bm25", "dify"}
    assert item["bm25_rank"] == 1
    assert item["dify_rank"] == 1


def test_bm25_reserved_reason():
    result = fuse_candidates(
        [_c("b1", "bm25 only content")],
        [],
        top_n=None,
    )
    assert result[0]["candidate_reason"] == "bm25_reserved"
    assert result[0]["source_hits"] == ["bm25"]
    assert result[0]["bm25_rank"] == 1
    assert result[0]["dify_rank"] is None


def test_dify_reserved_reason():
    result = fuse_candidates(
        [],
        [_c("d1", "dify only content")],
        top_n=None,
    )
    assert result[0]["candidate_reason"] == "dify_reserved"
    assert result[0]["source_hits"] == ["dify"]
    assert result[0]["dify_rank"] == 1
    assert result[0]["bm25_rank"] is None


def test_rrf_selected_reason_for_low_rank():
    # 10 BM25-only candidates: ranks 1-3 get bm25_reserved, ranks 4-10 get rrf_selected
    bm25 = [_c(f"b{i}", f"bm25 unique content {i}") for i in range(10)]
    result = fuse_candidates(bm25, [], top_n=None)
    reasons = {item["bm25_rank"]: item["candidate_reason"] for item in result}
    assert reasons[1] == "bm25_reserved"
    assert reasons[2] == "bm25_reserved"
    assert reasons[3] == "bm25_reserved"
    assert reasons[4] == "rrf_selected"
    assert reasons[10] == "rrf_selected"


def test_top_none_passes_all_through():
    bm25 = [_c(f"b{i}", f"bm25 {i}") for i in range(10)]
    dify = [_c(f"d{i}", f"dify {i}") for i in range(10)]
    result = fuse_candidates(bm25, dify, top_n=None)
    assert len(result) == 20


def test_source_balanced_truncation_protects_dify_high_rank():
    """双源中文候选占满 RRF 前列时，Dify 高排名单源候选仍能进入 top_n。"""
    multi = [_c(f"m{i}", f"shared content {i}") for i in range(5)]
    bm25_extra = [_c(f"b{i}", f"bm25 extra {i}") for i in range(5)]
    # Dify 侧：单源候选排 rank 1，双源候选排 2-6
    dify_only = [_c("dify-star", "dify only star content")]
    result = fuse_candidates(
        multi + bm25_extra,          # BM25 ranks: m0-4=1-5, b0-4=6-10
        dify_only + multi,           # Dify ranks: dify-star=1, m0-4=2-6
        top_n=6,
        reserve_n=1,
    )
    chunk_ids = [item["chunk_id"] for item in result]
    assert "dify-star" in chunk_ids
    star = next(item for item in result if item["chunk_id"] == "dify-star")
    assert star["candidate_reason"] == "dify_reserved"


def test_source_balanced_truncation_protects_bm25_high_rank():
    multi = [_c(f"m{i}", f"shared content {i}") for i in range(5)]
    dify_extra = [_c(f"d{i}", f"dify extra {i}") for i in range(5)]
    # BM25 侧：单源候选排 rank 1，双源候选排 2-6
    bm25_only = [_c("bm25-star", "bm25 only star content")]
    result = fuse_candidates(
        bm25_only + multi,           # BM25 ranks: bm25-star=1, m0-4=2-6
        multi + dify_extra,          # Dify ranks: m0-4=1-5, d0-4=6-10
        top_n=6,
        reserve_n=1,
    )
    chunk_ids = [item["chunk_id"] for item in result]
    assert "bm25-star" in chunk_ids
    star = next(item for item in result if item["chunk_id"] == "bm25-star")
    assert star["candidate_reason"] == "bm25_reserved"


def test_no_language_or_document_special_casing():
    """formal / 英文文档不应获得特殊加分，仅靠 source 保底进入。"""
    # formal 英文文档在 Dify rank 5（超出 reserve_n=3），应被标记为 rrf_selected
    # 而非通过任何文档特判进入
    dify = [
        _c(f"d{i}", f"dify content {i}", source_file="ZRDDS用户手册.pdf") for i in range(4)
    ] + [
        _c("formal-en", "formal english read take semantics", source_file="formal-15-04-10")
    ]
    result = fuse_candidates([], dify, top_n=None, reserve_n=3)
    formal = next(item for item in result if item["chunk_id"] == "formal-en")
    assert formal["dify_rank"] == 5
    assert formal["candidate_reason"] == "rrf_selected"
    # 但如果 top_n 足够大且 RRF 分数够，它仍能通过 rrf_selected 进入
    assert formal["source_hits"] == ["dify"]


def test_dedup_preserves_both_source_ranks():
    result = fuse_candidates(
        [_c("shared", "same content")],
        [_c("shared", "same content")],
        top_n=None,
    )
    item = result[0]
    assert item["bm25_rank"] == 1
    assert item["dify_rank"] == 1
    assert set(item["source_hits"]) == {"bm25", "dify"}
