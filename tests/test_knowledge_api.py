from fastapi.testclient import TestClient

from app.main import app
from app.schemas.knowledge import KnowledgeQuery
from app.services.knowledge_service import KnowledgeService


def test_knowledge_api_preserves_evidence_fields_and_ranking():
    response = TestClient(app).post(
        "/api/v1/knowledge/search",
        json={
            "keyword": "Psapi.lib 丢失怎么办",
            "version": None,
            "product": "ZRDDS",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    results = response.json()
    assert results
    top1 = results[0]
    assert top1["chunk_id"] == "chunk-0042"
    assert top1["content"]
    assert top1["section"]
    assert top1["document_id"] == "zrdds_troubleshooting"
    assert top1["doc_name"] == "ZRDDS故障排查指南.pdf"
    assert top1["product"] == "ZRDDS"
    assert top1["version"] is None
    assert top1["version_status"] == "unknown"
    assert top1["source_pages"]
    assert isinstance(top1["score"], float)


def test_knowledge_api_accepts_empty_and_null_version():
    for version in ("", None):
        response = TestClient(app).post(
            "/api/v1/knowledge/search",
            json={"keyword": "配置", "version": version, "product": "ZRDDS", "top_k": 3},
        )
        assert response.status_code == 200
        assert response.json()

def test_knowledge_search_returns_ranked_results():
    q = KnowledgeQuery(keyword="配置", top_k=3)
    results = KnowledgeService.search(q)
    print(f"命中 {len(results)} 条")
    for r in results:
        print(f"  {r.doc_name} 得分: {r.score:.2f}")
        print(f"  片段: {r.content[:50]}...")
    assert results
    assert len(results) <= 3
    assert all(result.content and result.doc_name for result in results)


def test_unknown_version_returns_no_incompatible_results():
    results = KnowledgeService.search(
        KnowledgeQuery(keyword="配置", version="v2.0", top_k=3)
    )
    # 当前元数据未声明文档版本，保守策略是不把 unknown 当作 compatible。
    assert results == []

if __name__ == "__main__":
    test_version_filter()
