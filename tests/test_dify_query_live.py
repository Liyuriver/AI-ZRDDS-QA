# -*- coding: utf-8 -*-
"""真实 Dify 集成回归（运行需网络 + backend/.env，标记为 live）。

A. 中文 → 中文文档：6 题全链路（retrieval + rerank + evidence + LLM），不得新增失败。
B. 中文 → 英文文档：5 题，Dify Top-10 命中率 >= 80%，Top-20 >= 90%。
C. 英文 → 英文文档：5 题，Dify Top-10 命中率 >= 80%。
read/take 专项：query <= 250，保留 read/take/SampleStateKind，Top-10 命中核心 formal 证据。
命中定义：Top-K 中出现 formal-15-04-10 文档的 segment，且其内容包含该题概念关键词。
"""

import asyncio
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1] / "backend"
load_dotenv(BACKEND / ".env")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import BM25_TOP_K, DIFY_TOP_K, RERANK_TOP_N, RRF_K  # noqa: E402
from app.services.ai_client import DIFY_QUERY_MAX_LENGTH, AIClient, build_dify_query  # noqa: E402
from app.services.query_rewrite_service import rewrite_query  # noqa: E402
from app.services.retrieval.evidence_service import select_evidence  # noqa: E402
from app.services.retrieval.fusion_service import fuse_candidates  # noqa: E402
from app.services.retrieval.rerank_service import rerank  # noqa: E402
from app.services.retrieval.retrieval_service import retrieve_candidates  # noqa: E402

pytestmark = pytest.mark.live

READTAKE_Q = "订阅端反复读取到同一批样本，开发者怀疑读取接口选择不当。应如何从 read/take 语义与样本状态角度定位？"

ZH_ZH = [
    "DataReader 的 Listener 回调里执行阻塞操作可能导致死锁，应如何避免？",
    "如何使用 WaitSet 和 Condition 等待多个 DDS 状态同时满足？",
    "SampleInfo 中 valid_data 字段的含义是什么？什么时候为 false？",
    "on_data_available 与 on_data_on_readers 回调的区别是什么？",
    "InstanceStateKind 有哪几种取值？disposed 与 no_writers 分别表示什么？",
    "ReadCondition 和 StatusCondition 有什么区别？",
]

ZH_EN = [
    ("DataReader 中 sample_state 有哪两种取值？read 之后样本状态会变成什么？", ["sample_state"]),
    ("view_state 与 sample_state 有什么区别？", ["view_state"]),
    ("instance_state 的 disposed 与 no_writers 状态分别表示什么？", ["instance_state", "disposed"]),
    ("ReliabilityQosPolicy 如何区分可靠传输与尽力而为传输？", ["reliability"]),
    ("HistoryQosPolicy、DeadlineQosPolicy、LivelinessQosPolicy 分别控制什么行为？", ["liveliness", "deadline"]),
]

EN_EN = [
    ("In DDS, what is the meaning of READ_SAMPLE_STATE and when does a sample become NOT_READ_SAMPLE_STATE?", ["sample_state"]),
    ("What is the difference between view_state and instance_state in DDS SampleInfo?", ["view_state", "instance_state"]),
    ("How does ReliabilityQosPolicy switch between reliable and best_effort delivery?", ["reliability"]),
    ("What do history_depth and deadline period control in a DDS DataWriter?", ["history_depth", "deadline"]),
    ("Under what conditions is LIVELINESS_CHANGED_STATUS raised for a DataReader?", ["liveliness"]),
]

_ZH_EN_RESULTS: list[dict] = []
_EN_EN_RESULTS: list[dict] = []


def _retrieve(question: str, top_k: int = 20):
    ai = AIClient()
    rewritten = rewrite_query(question)
    dify = asyncio.run(
        ai.retrieve_knowledge(rewritten.search_query, top_k=top_k, original_query=question)
    )
    return ai, rewritten, dify


def _formal_concept_hit(records: list[dict], k: int, concepts: list[str]) -> bool:
    for item in records[:k]:
        doc = str(item.get("source_file") or item.get("document") or "")
        content = str(item.get("content") or "").lower()
        if "formal" in doc.lower() and any(concept in content for concept in concepts):
            return True
    return False


# ---------- A. 中文 → 中文：6 题全链路，不得新增失败 ----------
@pytest.mark.parametrize("question", ZH_ZH)
def test_zh_zh_full_pipeline(question: str):
    rewritten = rewrite_query(question)
    query = build_dify_query(question, rewritten.search_query)
    assert len(query) <= DIFY_QUERY_MAX_LENGTH

    bm25 = retrieve_candidates(rewritten.search_query, top_k=BM25_TOP_K)
    ai = AIClient()
    dify = asyncio.run(
        ai.retrieve_knowledge(rewritten.search_query, top_k=DIFY_TOP_K, original_query=question)
    )
    assert ai.last_retrieval_trace["status"] == "success", ai.last_retrieval_trace
    assert dify, question

    fused = fuse_candidates(bm25, dify, rrf_k=RRF_K, top_n=None)
    reranked = rerank(question, fused, top_n=RERANK_TOP_N)
    evidence = select_evidence(question, reranked, top_n=RERANK_TOP_N)
    assert evidence, question

    context = "\n\n".join(
        f"[证据{index}]\n来源：{item.get('source_file', '')}\n章节：{item.get('section', '')}\n内容：{item.get('content', '')}"
        for index, item in enumerate(evidence, 1)
    )
    result = asyncio.run(
        ai.query(
            question=question,
            version=None,
            conversation_id="",
            user_id="zh-zh-reg",
            external_context=context,
            evidence=evidence,
        )
    )
    assert result["answer_status"] == "ANSWER", (question, result.get("answer"))


# ---------- B. 中文 → 英文：5 题命中率 ----------
@pytest.mark.parametrize("question,concepts", ZH_EN)
def test_zh_en_individual(question: str, concepts: list[str]):
    ai, rewritten, dify = _retrieve(question, top_k=20)
    _ZH_EN_RESULTS.append({
        "question": question,
        "hit10": _formal_concept_hit(dify, 10, concepts),
        "hit20": _formal_concept_hit(dify, 20, concepts),
        "query_length": len(ai.last_retrieval_trace.get("dify_query", "")),
    })


def test_zh_en_hit_rates():
    n = len(_ZH_EN_RESULTS)
    assert n == len(ZH_EN), _ZH_EN_RESULTS
    hit10 = sum(item["hit10"] for item in _ZH_EN_RESULTS) / n
    hit20 = sum(item["hit20"] for item in _ZH_EN_RESULTS) / n
    assert hit10 >= 0.8, _ZH_EN_RESULTS
    assert hit20 >= 0.9, _ZH_EN_RESULTS
    assert all(item["query_length"] <= DIFY_QUERY_MAX_LENGTH for item in _ZH_EN_RESULTS)


# ---------- C. 英文 → 英文：5 题命中率 ----------
@pytest.mark.parametrize("question,concepts", EN_EN)
def test_en_en_individual(question: str, concepts: list[str]):
    ai, rewritten, dify = _retrieve(question, top_k=20)
    _EN_EN_RESULTS.append({
        "question": question,
        "hit10": _formal_concept_hit(dify, 10, concepts),
        "hit20": _formal_concept_hit(dify, 20, concepts),
        "query_length": len(ai.last_retrieval_trace.get("dify_query", "")),
    })


def test_en_en_hit_rates_and_no_regression():
    n = len(_EN_EN_RESULTS)
    assert n == len(EN_EN), _EN_EN_RESULTS
    hit10 = sum(item["hit10"] for item in _EN_EN_RESULTS) / n
    # C 组规格：Top-10 命中率 >= 80%；Top-20 仅记录用于报告，不作硬门槛
    assert hit10 >= 0.8, _EN_EN_RESULTS
    assert all(item["query_length"] <= DIFY_QUERY_MAX_LENGTH for item in _EN_EN_RESULTS)


# ---------- read/take 专项验收 ----------
def test_readtake_acceptance():
    ai, rewritten, dify = _retrieve(READTAKE_Q, top_k=DIFY_TOP_K)
    trace = ai.last_retrieval_trace
    query = trace.get("dify_query", "")
    assert len(query) <= DIFY_QUERY_MAX_LENGTH
    for term in ("read", "take", "SampleStateKind"):
        assert term.casefold() in query.casefold(), (term, query)
    assert trace["status"] == "success", trace

    core = [
        item
        for item in dify[:DIFY_TOP_K]
        if "formal" in str(item.get("source_file") or "").lower()
        and "read_next_sample" in str(item.get("content") or "").lower()
        and any(
            marker in str(item.get("content") or "").lower()
            for marker in ("no longer", "removed", "cannot be read", "not be accessed", "not be returned")
        )
    ]
    assert core, [str(item.get("source_file")) for item in dify[:DIFY_TOP_K]]
