"""Offline regression for generic multi-facet evidence coverage."""

from app.services.answer_validation_service import soften_unverified_negative_claims, validate_answer
from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.evidence_service import (
    analyze_evidence_support,
    build_facet_trace,
    extract_facet_requirements,
    select_evidence,
)
from app.services.retrieval.retrieval_service import retrieve_candidates


def _candidate(identifier, content, score):
    return {"chunk_id": identifier, "content": content, "rerank_score": score, "fusion_score": score}


def test_explicit_technical_entities_are_required_without_dds_term_list():
    rewritten = rewrite_query("Compare AlphaPolicy, BetaPolicy and GAMMA_STATE separately")
    assert {"AlphaPolicy", "BetaPolicy", "GAMMA_STATE"} <= set(rewritten.required_facets)


def test_lower_ranked_required_facets_survive_final_top5():
    query = "DeadlineQosPolicy 与 LivelinessQosPolicy 分别控制什么？"
    requirements = extract_facet_requirements(query)
    pool = [
        _candidate("high-general", "QoS overview and common configuration", .99),
        _candidate("deadline", "DeadlineQosPolicy defines a deadline period.", .50),
        _candidate("liveliness", "LivelinessQosPolicy controls liveliness assertion.", .40),
    ]
    selected = select_evidence(query, pool, top_n=2, requirements=requirements)
    assert {item["chunk_id"] for item in selected} == {"deadline", "liveliness"}
    assert selected[0]["uncovered_facets"] == []


def test_sample_case_has_coverage_before_score_fill():
    query = "SAMPLE_REJECTED 和 SAMPLE_LOST，结合 History 与 ResourceLimits 分析。"
    requirements = extract_facet_requirements(query)
    pool = [
        _candidate("overview", "Generic high scoring data overview", .99),
        _candidate("rejected", "SAMPLE_REJECTED occurs when ResourceLimits rejects a sample.", .35),
        _candidate("lost", "SAMPLE_LOST is reported after lost samples; History affects retained samples.", .34),
    ]
    selected = select_evidence(query, pool, top_n=3, requirements=requirements)
    ids = {item["chunk_id"] for item in selected}
    assert {"rejected", "lost"} <= ids
    assert not selected[0]["uncovered_facets"]


def test_real_bm25_sample_rejected_evidence_survives_final_selection():
    query = "高频数据场景中出现SAMPLE_REJECTED或SAMPLE_LOST。请给出从History、ResourceLimits、读取速度和网络可靠性几个方向的排查路径。"
    requirements = extract_facet_requirements(query)
    pool = retrieve_candidates(rewrite_query(query).search_query, top_k=30)
    for item in pool:
        item["rerank_score"] = float(item.get("raw_score") or 0)
    selected = select_evidence(query, pool, top_n=5, requirements=requirements)
    assert any("sample_rejected" in str(item.get("content") or "").lower() for item in selected)
    assert {"SAMPLE_REJECTED", "SAMPLE_LOST", "History", "ResourceLimits"} <= set(selected[0]["covered_facets"])


def test_trace_locates_first_loss_at_rerank():
    query = "AlphaAPI 与 BetaAPI 的区别"
    requirements = extract_facet_requirements(query)
    alpha, beta = _candidate("alpha", "AlphaAPI details", .9), _candidate("beta", "BetaAPI details", .1)
    trace = build_facet_trace({"bm25": [alpha, beta], "fusion": [alpha, beta], "rerank": [alpha], "evidence": [alpha]}, requirements["required_facets"])
    assert trace["first_seen_stage"]["BetaAPI"] == "bm25"
    assert trace["first_lost_stage"]["BetaAPI"] == "rerank"


def test_validation_blocks_negative_claim_when_pool_supports_facet():
    query = "Explain CONFIG_A and CONFIG_B"
    requirements = extract_facet_requirements(query)
    final = [_candidate("a", "CONFIG_A definition", .9)]
    pool = final + [_candidate("b", "CONFIG_B definition", .2)]
    result = validate_answer("The knowledge base does not contain CONFIG_B.", final, query, candidate_pool=pool, required_facets=requirements["required_facets"])
    assert "CONFIG_B" in result.negative_claim_facets
    assert result.should_retry
    assert "does not contain" not in soften_unverified_negative_claims("The knowledge base does not contain CONFIG_B.").lower()


def test_compositional_evidence_supports_a_change_risk_without_scenario_quote():
    query = "SchemaKit 更新后只替换部分 AdapterSet 产物会有什么风险？"
    requirements = extract_facet_requirements(query)
    evidence = [
        _candidate("origin", "SchemaKit generates the AdapterSet artifacts from a schema.", .8),
        _candidate("role", "AdapterSet provides type support, serialization and typed interfaces.", .7),
        _candidate("outcome", "Same names with different internal structures can cause deserialization failure.", .6),
    ]
    support = analyze_evidence_support(query, evidence, requirements["required_facets"])
    assert support["compositionally_covered_facets"]
    assert not support["unsupported_facets"]
    result = validate_answer(
        "Partial replacement creates a compatibility risk.", evidence, query,
        candidate_pool=evidence, required_facets=requirements["required_facets"],
    )
    assert not result.should_retry
    refusal = validate_answer(
        "The documentation does not describe this exact scenario; evidence is insufficient.", evidence, query,
        candidate_pool=evidence, required_facets=requirements["required_facets"],
    )
    assert refusal.compositional_refusal_facets
    assert refusal.should_retry


def test_missing_a_required_relation_remains_unsupported():
    query = "SchemaKit 更新后只替换部分 AdapterSet 产物会造成 FailureMode 吗？"
    requirements = extract_facet_requirements(query)
    evidence = [
        _candidate("origin", "SchemaKit generates the AdapterSet artifacts from a schema.", .8),
        _candidate("role", "AdapterSet provides type support and serialization.", .7),
    ]
    support = analyze_evidence_support(query, evidence, requirements["required_facets"])
    assert not support["compositionally_covered_facets"]
    assert support["unsupported_facets"]


def test_unrelated_multifacet_and_singlefacet_regressions():
    cases = [
        ("Topic、Type、Partition 的匹配条件", ["Topic", "Type", "Partition"]),
        ("Compare create_session / close_session / SESSION_TIMEOUT", ["create_session", "close_session", "SESSION_TIMEOUT"]),
        ("解释 BufferSize、RetryPolicy 和 TLS_MODE", ["BufferSize", "RetryPolicy", "TLS_MODE"]),
        ("How does ContentFilteredTopic work?", ["ContentFilteredTopic"]),
    ]
    for query, expected in cases:
        requirements = extract_facet_requirements(query)
        required = {facet["id"] for facet in requirements["required_facets"]}
        assert set(expected) <= required
        pool = [_candidate(term, f"{term} documented behavior", .2 + index / 100) for index, term in enumerate(expected)]
        selected = select_evidence(query, pool, top_n=5, requirements=requirements)
        assert not selected[0]["uncovered_facets"]
