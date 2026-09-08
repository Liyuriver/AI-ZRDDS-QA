"""Facet-aware evidence selection for the final answer context."""

from __future__ import annotations

import re
from typing import Any

from app.services.query_rewrite_service import rewrite_query


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}")
_FACET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("instance_registration", ("实例注册", "注册实例", "register_instance", "register")),
    ("write", ("datawriter_write", "write", "写入", "写数据")),
    ("dispose", ("dispose", "销毁实例", "释放实例")),
    ("read", ("read", "读取")),
    ("take", ("take", "取出")),
    ("listener", ("listener", "监听器", "回调")),
    ("waitset", ("waitset", "wait set", "同步等待")),
    ("condition", ("readcondition", "statuscondition", "querycondition", "condition")),
    ("qos", ("qos", "服务质量")),
    ("reliability", ("reliability", "可靠性", "best_effort", "reliable")),
    ("history", ("history", "历史")),
    ("resource_limits", ("resourcelimits", "resource_limits", "资源限制", "资源上限")),
    ("durability", ("durability", "持久性")),
    ("partition", ("partition", "分区")),
    ("topic", ("topic", "主题")),
    ("type", ("数据类型", "类型一致", "类型不一致", "type")),
    ("domain", ("domainparticipant", "domain id", "domain")),
    ("idl", ("idl", "结构体")),
    ("serialization", ("序列化", "serialize")),
    ("deserialization", ("反序列化", "deserialize")),
    ("xml_qos", ("xml", "xml qos", "配置文件")),
    ("network", ("网络", "端口", "传输", "发现")),
    ("logging", ("日志", "计数器", "状态")),
    ("blocking", ("阻塞", "卡住", "锁竞争", "死锁")),
    ("api_lifecycle", ("api", "创建", "生命周期", "调用顺序")),
)

_SCENARIO_ALIASES = (
    "收不到数据", "无样本", "看不到", "看不到消息", "没有数据", "丢消息", "数据丢失",
    "通信失败", "故障", "异常",
)


def _tokens(value: Any) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(value or "").lower())}


def _facets_for_text(text: str) -> set[str]:
    lowered = text.lower()
    return {facet for facet, aliases in _FACET_ALIASES if any(alias.lower() in lowered for alias in aliases)}


def _scenario_terms(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({term for term in _SCENARIO_ALIASES if term.lower() in lowered})


def _query_facets(query: str) -> set[str]:
    rewritten = rewrite_query(query)
    text = " ".join((rewritten.original_query, *rewritten.core_terms, *rewritten.technical_entities,
                      *rewritten.scenario_terms, *rewritten.expansion_terms))
    facets = _facets_for_text(text)
    if "实例" in query and any(x in query for x in ("注册", "写")):
        facets.add("instance_registration")
    if "dispose" in query.lower() or "销毁" in query:
        facets.add("dispose")
    if "资源限制" in query:
        facets.add("resource_limits")
    if "xml" in query.lower() and "qos" in query.lower():
        facets.add("xml_qos")
    if "api" in query.lower() or "调用顺序" in query:
        facets.add("api_lifecycle")
    return facets


def _language(text: str) -> str:
    lowered = text.lower()
    if "java" in lowered or "jvm" in lowered:
        return "java"
    if "c++" in lowered or "cpp" in lowered:
        return "cpp"
    if re.search(r"\bc\b|c语言", lowered):
        return "c"
    return "generic"


def _same_topic_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_section = re.sub(r"\b(c\+\+|cpp|java|c语言|c)\b", "", str(left.get("section") or "").lower())
    right_section = re.sub(r"\b(c\+\+|cpp|java|c语言|c)\b", "", str(right.get("section") or "").lower())
    if left_section and right_section and left_section == right_section:
        return True
    left_text = " ".join(str(left.get(key) or "") for key in ("section", "heading_path", "content"))
    right_text = " ".join(str(right.get(key) or "") for key in ("section", "heading_path", "content"))
    left_tokens, right_tokens = _tokens(left_text), _tokens(right_text)
    return bool(left_tokens and right_tokens) and len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1) >= 0.82


def _annotate(item: dict[str, Any], detected: set[str], covered: set[str], uncovered: set[str]) -> None:
    text = " ".join(str(item.get(key) or "") for key in ("section", "heading_path", "content"))
    item["evidence_facets"] = sorted(_facets_for_text(text) & detected)
    item["detected_facets"] = sorted(detected)
    item["covered_facets"] = sorted(covered)
    item["uncovered_facets"] = sorted(uncovered)


def select_evidence(query: str, candidates: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    """Cover relevant query facets, then prefer rerank score and diversity."""
    if not candidates or top_n <= 0:
        return []
    detected = _query_facets(query)
    scenario_terms = _scenario_terms(query)
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    covered: set[str] = set()
    requested_language = _language(query)
    query_terms = _tokens(query)

    while remaining and len(selected) < top_n:
        best = None
        best_key = None
        for item in remaining:
            text = " ".join(str(item.get(key) or "") for key in ("section", "heading_path", "content"))
            item_facets = _facets_for_text(text) & detected
            gain = item_facets - covered
            item_language = _language(" ".join(str(item.get(key) or "") for key in ("source_file", "section", "content")))
            duplicate = any(_same_topic_group(item, chosen) for chosen in selected)
            language_exception = requested_language != "generic" and item_language == requested_language
            duplicate_penalty = 0.12 if duplicate and not language_exception else 0.0
            overlap = len(query_terms & _tokens(text))
            score = float(item.get("rerank_score", 0) or 0)
            # Coverage is only a bounded tie-breaker while facets remain. It
            # cannot make a low-relevance candidate beat a clearly relevant one.
            key = (score + 0.20 * len(gain) + overlap * 0.001
                   + (0.015 if not duplicate else 0.0) - duplicate_penalty,
                   float(len(gain)), score, float(overlap),
                   str(item.get("id") or item.get("chunk_id") or ""))
            if best_key is None or key > best_key:
                best, best_key = item, key
        if best is None:
            break
        remaining.remove(best)
        text = " ".join(str(best.get(key) or "") for key in ("section", "heading_path", "content"))
        covered.update(_facets_for_text(text) & detected)
        best["evidence_rank"] = len(selected) + 1
        selected.append(best)

    uncovered = detected - covered
    for item in selected:
        _annotate(item, detected, covered, uncovered)
        item["scenario_terms"] = scenario_terms
    return selected
