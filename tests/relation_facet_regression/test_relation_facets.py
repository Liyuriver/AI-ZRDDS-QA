from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.evidence_service import (
    analyze_evidence_support,
    build_relation_recovery_query,
    extract_facet_requirements,
    select_evidence,
)
from app.services.answer_validation_service import validate_answer


def test_rewrite_extracts_roles_and_constraint_without_policy_vocabulary():
    rewritten = rewrite_query("ProducerA provides API; ConsumerB requires API; versions must be compatible.")
    relations = rewritten.relation_facets
    assert {item["relation"] for item in relations} >= {"offers", "requests", "matches"}
    assert {item["subject"] for item in relations} >= {"ProducerA", "ConsumerB"}


def test_selector_hard_covers_bilateral_relation_and_rule():
    query = "Writer and Reader must match on Reliability: Writer offers, Reader requests."
    requirements = extract_facet_requirements(query)
    candidates = [
        {"chunk_id": "generic", "content": "Writer and Reader use QoS." , "rerank_score": .99},
        {"chunk_id": "offer", "content": "DataWriter offers Reliability to the matched endpoint.", "rerank_score": .8},
        {"chunk_id": "request", "content": "DataReader requests Reliability from the remote endpoint.", "rerank_score": .7},
        {"chunk_id": "rule", "content": "The Reliability compatibility rule requires the offered value to satisfy the requested value.", "rerank_score": .6},
    ]
    selected = select_evidence(query, candidates, 3, requirements=requirements)
    ids = {item["chunk_id"] for item in selected}
    assert {"offer", "request", "rule"} <= ids
    support = analyze_evidence_support(query, selected, requirements["required_facets"], requirements["required_relation_facets"])
    assert support["relation_chain_supported"]
    assert not support["uncovered_relation_facets"]


def test_missing_relation_builds_one_bounded_recovery_query():
    query = "ProducerA provides API and ConsumerB requires API; versions must be compatible."
    requirements = extract_facet_requirements(query)
    recovery = build_relation_recovery_query(query, requirements["required_relation_facets"], [
        {"chunk_id": "unrelated", "content": "API overview only."}
    ])
    assert recovery
    assert "ProducerA" in recovery and "ConsumerB" in recovery
    assert recovery.count("compatibility") == 1


def test_negative_claim_is_rejected_when_relation_candidates_support_it():
    query = "ProducerA provides API and ConsumerB requires API; versions must be compatible."
    requirements = extract_facet_requirements(query)
    pool = [
        {"chunk_id": "a", "content": "ProducerA provides API."},
        {"chunk_id": "b", "content": "ConsumerB requires API."},
        {"chunk_id": "c", "content": "API versions have a compatibility rule."},
    ]
    result = validate_answer(
        "知识库没有版本兼容规则，因此无法判断。",
        [], query, candidate_pool=pool,
        required_facets=requirements["required_facets"],
        relation_facets=requirements["required_relation_facets"],
    )
    assert result.should_retry
