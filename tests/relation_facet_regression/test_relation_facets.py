from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.evidence_service import (
    analyze_evidence_support,
    build_facet_recovery_query,
    build_facet_trace,
    build_relation_recovery_query,
    effective_evidence_changed,
    extract_facet_requirements,
    relation_coverage,
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


def test_recovery_relation_is_selected_by_identity_and_not_only_rank():
    query = "Writer and Reader must match on Reliability: Writer offers, Reader requests."
    requirements = extract_facet_requirements(query)
    relation_candidates = [
        {"chunk_id": "writer", "content": "DataWriter offers Reliability.", "rerank_score": .99},
        {"chunk_id": "reader", "content": "DataReader requests Reliability.", "rerank_score": .98},
        {"chunk_id": "recovery-rule", "content": "The offered Reliability must satisfy the requested Reliability according to the compatibility rule.", "rerank_score": .05, "recovery_retrieval": True},
    ]
    relation_map = {"2": ["recovery-rule"]}
    selected = select_evidence(
        query,
        relation_candidates,
        top_n=3,
        requirements=requirements,
        force_relation_ids=relation_map,
        preferred_candidate_ids={"recovery-rule"},
        recovery_support_map=relation_map,
    )
    ids = {item["chunk_id"] for item in selected}
    assert "recovery-rule" in ids
    assert any("recovery-rule" in item["recovery_support_map"].get("2", []) for item in selected)
    support = analyze_evidence_support(query, selected, requirements["required_facets"], requirements["required_relation_facets"])
    assert not support["uncovered_relation_facets"]


def test_retry_change_is_effective_only_when_missing_target_support_changes():
    requirements = extract_facet_requirements(
        "Writer offers API; Reader requests API; versions must be compatible."
    )
    first = [{"chunk_id": "writer", "content": "Writer offers API versions be."}]
    unrelated_retry = [
        {"chunk_id": "writer", "content": "Writer offers API versions be."},
        {"chunk_id": "unrelated", "content": "General API overview."},
    ]
    fixed_retry = [
        {"chunk_id": "writer", "content": "Writer offers API versions be."},
        {"chunk_id": "rule", "content": "The offered API versions be must satisfy the requested API versions be compatibility rule."},
    ]
    assert not effective_evidence_changed(
        first, unrelated_retry, requirements, relation_ids={"2"}
    )
    assert effective_evidence_changed(
        first, fixed_retry, requirements, relation_ids={"2"}
    )


def test_facet_recovery_and_relation_trace_report_stage_loss():
    requirements = extract_facet_requirements("Explain AlphaAPI and BetaAPI")
    recovery_query = build_facet_recovery_query(
        "Explain AlphaAPI and BetaAPI",
        requirements["required_facets"],
        [{"chunk_id": "alpha", "content": "AlphaAPI documented behavior"}],
    )
    assert recovery_query and "BetaAPI" in recovery_query
    trace = build_facet_trace(
        {
            "bm25": [{"chunk_id": "rule", "content": "Writer offers API."}],
            "recovery": [{"chunk_id": "rule", "content": "Writer offers API."}],
            "evidence": [],
        },
        [],
        [{"subject": "Writer", "relation": "offers", "object": "API", "required": True}],
    )
    assert trace["relation_first_seen_stage"]["0"] == "bm25"
    assert trace["relation_first_lost_stage"]["0"] == "evidence"


def test_english_sentence_words_are_diagnostics_not_required_facets():
    query = "Writer and Reader are discovered but QoS is incompatible; their Reliability values differ. Determine whether the offered or requested side is unsatisfied."
    requirements = extract_facet_requirements(query)
    assert {facet["id"] for facet in requirements["required_facets"]} == {
        "Writer", "Reader", "QoS", "Reliability"
    }
    rejected = {
        item["facet"] for item in requirements["facet_diagnostics"]["rejected_noise_facets"]
    }
    assert {"are", "discovered", "but", "values", "Determine", "side"} <= rejected
    assert all(
        "are" not in str(relation["object"]).split()
        and "values" not in str(relation["object"]).split()
        for relation in requirements["required_relation_facets"]
    )


def test_relation_coverage_does_not_require_literal_subject_mentions_in_answer():
    query = "Writer and Reader are discovered but QoS is incompatible; their Reliability values differ. Determine whether the offered or requested side is unsatisfied."
    requirements = extract_facet_requirements(query)
    evidence = [
        {"chunk_id": "writer", "content": "DataWriter offers Reliability QoS."},
        {"chunk_id": "reader", "content": "DataReader requests Reliability QoS."},
        {"chunk_id": "rule", "content": "The offered QoS satisfies the requested QoS compatibility rule."},
    ]
    result = validate_answer(
        "The offered and requested Reliability QoS values are compared by the compatibility rule.",
        evidence,
        query,
        candidate_pool=evidence,
        required_facets=requirements["required_facets"],
        relation_facets=requirements["required_relation_facets"],
        facet_diagnostics=requirements["facet_diagnostics"],
    )
    assert result.status == "answered"
    assert not result.missing_required_facets
    assert {"Writer", "Reader"} <= set(result.ignored_missing_facets)


def test_true_missing_core_relation_still_triggers_validation():
    query = "Writer offers Reliability; Reader requests Reliability; the values must satisfy the compatibility rule."
    requirements = extract_facet_requirements(query)
    final = [
        {"chunk_id": "writer", "content": "DataWriter offers Reliability."},
        {"chunk_id": "rule", "content": "The offered Reliability satisfies the requested Reliability compatibility rule."},
    ]
    pool = final + [{"chunk_id": "reader", "content": "DataReader requests Reliability."}]
    result = validate_answer(
        "The offered Reliability is checked against the requested Reliability.",
        final,
        query,
        candidate_pool=pool,
        required_facets=requirements["required_facets"],
        relation_facets=requirements["required_relation_facets"],
        facet_diagnostics=requirements["facet_diagnostics"],
    )
    assert result.should_retry
    assert "relation:1" in result.missing_relations


def test_presence_without_concrete_constraint_triggers_recovery():
    query = "Writer offers API; Reader requests API; API versions must be compatible."
    requirements = extract_facet_requirements(query)
    evidence = [
        {"chunk_id": "writer", "content": "Writer offers API."},
        {"chunk_id": "reader", "content": "Reader requests API."},
        {"chunk_id": "presence-only", "content": "API versions are compatible and have an RxO rule."},
    ]
    coverage = relation_coverage(evidence, requirements["required_relation_facets"])
    assert coverage["relation_presence_covered"] == ["0", "1", "2"]
    assert "2" not in coverage["relation_constraint_covered"]
    assert coverage["missing_relation_constraints"] == ["2"]
    assert build_relation_recovery_query(query, requirements["required_relation_facets"], evidence)
    validation = validate_answer(
        "Writer and Reader are mentioned, but the concrete compatibility ordering is not shown.",
        evidence,
        query,
        candidate_pool=evidence,
        required_facets=requirements["required_facets"],
        relation_facets=requirements["required_relation_facets"],
    )
    assert "relation:2" in validation.missing_relation_constraints
    assert validation.should_retry


def test_constraint_from_another_technical_object_cannot_be_borrowed():
    relation = {
        "subject": "Writer",
        "relation": "matches",
        "object": "BetaAPI",
        "constraint_type": "compatibility_rule",
        "required": True,
    }
    evidence = [{
        "chunk_id": "alpha-rule",
        "content": "DataWriter and DataReader AlphaAPI compatibility rule: AlphaAPI > AlphaAPI.",
    }]
    coverage = relation_coverage(evidence, [relation])
    assert coverage["relation_presence_covered"] == []
    assert coverage["relation_constraint_covered"] == []
    assert coverage["missing_relation_constraints"] == ["0"]


def test_same_technical_object_with_concrete_constraint_does_not_recover():
    query = "Writer offers API; Reader requests API; API versions must be compatible."
    requirements = extract_facet_requirements(query)
    evidence = [
        {"chunk_id": "writer", "content": "Writer offers API."},
        {"chunk_id": "reader", "content": "Reader requests API."},
        {"chunk_id": "rule", "content": "DataWriter API and DataReader API matching rule: API > API."},
    ]
    coverage = relation_coverage(evidence, requirements["required_relation_facets"])
    assert coverage["relation_presence_covered"] == ["0", "1", "2"]
    assert coverage["relation_constraint_covered"] == ["0", "1", "2"]
    assert coverage["missing_relation_constraints"] == []
    assert build_relation_recovery_query(query, requirements["required_relation_facets"], evidence) is None
