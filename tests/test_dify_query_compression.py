# -*- coding: utf-8 -*-
"""build_dify_query 通用压缩器：单元回归（无网络）。

覆盖：长度约束、中/英/中英混合、技术词保留、语义短语保留、
去重、related 丢弃、超长压缩、trace 契约、无单题 hardcode。
"""

import pytest

from app.services.ai_client import DIFY_QUERY_MAX_LENGTH, build_dify_query
from app.services.query_rewrite_service import rewrite_query

READTAKE_Q = "订阅端反复读取到同一批样本，开发者怀疑读取接口选择不当。应如何从 read/take 语义与样本状态角度定位？"
EN_Q = (
    "In DDS, what is the semantic difference between DataReader::read() and "
    "DataReader::take()? How do READ_SAMPLE_STATE and NOT_READ_SAMPLE_STATE "
    "affect whether the same sample can be returned again?"
)

CASES = [
    READTAKE_Q,
    EN_Q,
    "如何使用 WaitSet 和 Condition 等待多个 DDS 状态同时满足？",
    "SampleInfo 中 valid_data 字段的含义是什么？什么时候为 false？",
    "DataReader 的 Listener 回调里执行阻塞操作可能导致死锁，应如何避免？",
    "on_data_available 与 on_data_on_readers 回调的区别是什么？",
    "InstanceStateKind 有哪几种取值？disposed 与 no_writers 分别表示什么？",
    "ReadCondition 和 StatusCondition 有什么区别？",
    "DataReader 中 sample_state 有哪两种取值？read 之后样本状态会变成什么？",
    "view_state 与 sample_state 有什么区别？",
    "instance_state 的 disposed 与 no_writers 状态分别表示什么？",
    "ReliabilityQosPolicy 如何区分可靠传输与尽力而为传输？",
    "HistoryQosPolicy、DeadlineQosPolicy、LivelinessQosPolicy 分别控制什么行为？",
    "In DDS, what is the meaning of READ_SAMPLE_STATE and when does a sample become NOT_READ_SAMPLE_STATE?",
    "What is the difference between view_state and instance_state in DDS SampleInfo?",
    "How does ReliabilityQosPolicy switch between reliable and best_effort delivery?",
    "What do history_depth and deadline period control in a DDS DataWriter?",
    "Under what conditions is LIVELINESS_CHANGED_STATUS raised for a DataReader?",
]


def _build(question: str) -> str:
    return build_dify_query(question, rewrite_query(question).search_query)


def test_all_queries_stay_within_limit():
    for case in CASES:
        query = _build(case)
        assert len(query) <= DIFY_QUERY_MAX_LENGTH, (case, len(query))


def test_readtake_keeps_core_terms_and_semantic_gloss():
    query = _build(READTAKE_Q)
    assert len(query) <= DIFY_QUERY_MAX_LENGTH
    for term in ("read", "take", "SampleStateKind"):
        assert term.casefold() in query.casefold(), (term, query)
    assert "removes it from DataReader" in query


def test_readtake_drops_loan_drift_term():
    query = _build(READTAKE_Q)
    assert "return_loan" not in query.casefold()


def test_english_query_unchanged_when_identifiers_present():
    query = _build(EN_Q)
    assert query == EN_Q


def test_dedupe_read_variants():
    rewritten = EN_Q + " " + " ".join(["read", "take"] * 30)
    query = build_dify_query(EN_Q, rewritten)
    assert query == EN_Q
    assert len(query) <= DIFY_QUERY_MAX_LENGTH


def test_no_per_question_hardcode():
    # 语义无关的 WaitSet 问题不得注入样本状态/read-take 专属内容
    query = _build("如何使用 WaitSet 和 Condition 等待多个 DDS 状态同时满足？")
    assert "return_loan" not in query.casefold()
    assert "READ_SAMPLE_STATE" not in query
    # 不包含任何单题专用标记（如直接把 gloss 写死在 query 里）
    assert "act of reading" not in query.casefold()


def test_chinese_english_mixed_keeps_identifiers():
    question = "DataReader 中 sample_state 有哪两种取值？read 之后样本状态会变成什么？"
    query = _build(question)
    assert len(query) <= DIFY_QUERY_MAX_LENGTH
    for term in ("DataReader", "sample_state", "read"):
        assert term.casefold() in query.casefold(), (term, query)


def test_oversized_original_compressed_not_sliced():
    long_q = (
        "In DDS, what is the semantic difference between DataReader::read and "
        "DataReader::take regarding sample states and loaned collections? "
    ) * 3
    long_q = long_q.strip()
    query = build_dify_query(long_q, long_q)
    assert len(query) <= DIFY_QUERY_MAX_LENGTH
    assert "DataReader::read" in query
    assert "DataReader::take" in query


def test_trace_records_compression_decision():
    trace: dict = {}
    build_dify_query(READTAKE_Q, rewrite_query(READTAKE_Q).search_query, trace=trace)
    for key in (
        "core_terms",
        "technical_terms",
        "semantic_phrases",
        "dropped_terms",
        "final_dify_query",
        "final_length",
    ):
        assert key in trace, key
    assert "return_loan" in trace["dropped_terms"]
    assert trace["semantic_phrases"]
    assert len(trace["final_dify_query"]) <= DIFY_QUERY_MAX_LENGTH
    assert trace["final_length"] == len(trace["final_dify_query"])


def test_secondary_standard_terms_kept_when_budget_allows():
    question = "DataReader 的 Listener 回调里执行阻塞操作可能导致死锁，应如何避免？"
    trace: dict = {}
    query = build_dify_query(question, rewrite_query(question).search_query, trace=trace)
    assert "on_data_available" in query.casefold()
    assert "DATA_AVAILABLE" in query
    assert "回调限制" not in query
