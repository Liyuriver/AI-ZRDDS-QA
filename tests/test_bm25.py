from app.services.retrieval.retrieval_service import RetrievalService
from app.services.retrieval.tokenizer import tokenize


def test_build_and_skip_pending_document():
    service = RetrievalService()
    response = service.build_index()
    assert len(response.indexed_documents) >= 4
    assert response.total_candidates > 0
    user_manual_pending = any(item.status == "pending_hybrid" and item.document_id == "zrdds_user_manual"
                              for item in response.skipped_documents)
    if user_manual_pending:
        assert "zrdds_user_manual" not in response.indexed_documents
    else:
        assert "zrdds_user_manual" in response.indexed_documents


def test_technical_tokens_and_metadata_follow_results():
    tokens = tokenize("Psapi.lib ZRDDS_JAVA.dll create_participant 2.3.3")
    assert "psapi.lib" in tokens
    assert "zrdds_java.dll" in tokens
    assert "create_participant" in tokens
    assert "2.3.3" in tokens

    service = RetrievalService()
    result = service.retrieve("Psapi.lib", top_k=3)
    assert result.results
    assert all(item.document_id and item.source_file for item in result.results)
    assert result.results[0].doc_type is not None
    assert all(result.results[i].score >= result.results[i + 1].score
               for i in range(len(result.results) - 1))


def test_filters_apply_before_ranking_and_empty_query_is_safe():
    service = RetrievalService()
    result = service.retrieve("配置", top_k=2, doc_type="安装配置手册-Java")
    assert result.results
    assert all(item.doc_type == "安装配置手册-Java" for item in result.results)
    assert service.retrieve("", top_k=5).results == []
    assert service.retrieve("__absent_technical_token_zzq__", top_k=5).results == []
