import pytest

from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.fusion_service import fuse_candidates
from app.services.retrieval.retrieval_service import retrieve_candidates


@pytest.mark.parametrize("question, expected", [
    ("DomainParticipant 创建失败如何排查？", "DomainParticipant"),
    ("QoS 可靠通信配置不匹配怎么办？", "QoS"),
    ("发布端和订阅端收不到数据如何检查？", "收不到数据"),
    ("如何生成 IDL 数据类型支持文件？", "生成文件"),
    ("DataReader 的 Listener 如何处理 DATA_AVAILABLE？", "DataReader"),
])
def test_generic_queries_retrieve_technical_evidence(question, expected):
    rewritten = rewrite_query(question)
    # The retrieval corpus now includes the processed DDS formal PDFs and CHM
    # manuals; keep this generic evidence smoke test independent of duplicate
    # document-family competition in the first ten BM25 slots.
    results = retrieve_candidates(rewritten.search_query, top_k=30)
    assert results
    haystack = "\n".join(
        f"{item.get('section', '')} {item.get('content', '')}" for item in results
    )
    assert expected.lower() in haystack.lower()


def test_all_unique_candidates_reach_rerank_pool():
    bm25 = [{"chunk_id": f"b-{i}", "content": f"bm25 {i}"} for i in range(10)]
    dify = [{"chunk_id": f"d-{i}", "content": f"dify {i}"} for i in range(10)]
    fused = fuse_candidates(bm25, dify, top_n=None)
    assert len(fused) == 20
