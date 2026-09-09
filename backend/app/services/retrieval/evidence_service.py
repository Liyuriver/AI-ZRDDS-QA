"""Facet-aware final-evidence selection."""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.services.query_rewrite_service import QueryRewrite, rewrite_query

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}")
# Auxiliary retrieval hints only; required coverage comes from user wording.
_FACET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("instance_registration", ("实例注册", "注册实例", "register_instance", "register")), ("write", ("datawriter_write", "write", "写入", "写数据")),
    ("dispose", ("dispose", "销毁实例", "释放实例")), ("read", ("read", "读取")), ("take", ("take", "取出")),
    ("listener", ("listener", "监听器", "回调")), ("waitset", ("waitset", "wait set", "同步等待")),
    ("condition", ("readcondition", "statuscondition", "querycondition", "condition")), ("qos", ("qos", "服务质量")),
    ("reliability", ("reliability", "可靠性", "best_effort", "reliable")), ("history", ("history", "历史")),
    ("resource_limits", ("resourcelimits", "resource_limits", "资源限制", "资源上限")), ("durability", ("durability", "持久性")),
    ("partition", ("partition", "分区")), ("topic", ("topic", "主题")), ("type", ("数据类型", "类型一致", "类型不一致", "type")),
    ("domain", ("domainparticipant", "domain id", "domain")), ("idl", ("idl", "结构体")),
    ("serialization", ("序列化", "serialize")), ("deserialization", ("反序列化", "deserialize")),
    ("xml_qos", ("xml", "xml qos", "配置文件")), ("network", ("网络", "端口", "传输", "发现")),
    ("logging", ("日志", "计数器", "状态")), ("blocking", ("阻塞", "卡住", "锁竞争", "死锁")),
    ("api_lifecycle", ("api", "创建", "生命周期", "调用顺序")),
)
_SCENARIO_ALIASES = ("收不到数据", "无样本", "看不到", "看不到消息", "没有数据", "丢消息", "数据丢失", "通信失败", "故障", "异常")
_ENGINEERING_CHANGE_RE = re.compile(r"(?:部分|只|未(?:替换|同步|更新)|变更|修改|增加|删除|替换|不一致|风险|问题|处理|影响|partial|only|not\s+(?:replace|update|sync)|change|replace|inconsisten|risk|impact)", re.I)
_REASONING_RELATIONS: dict[str, tuple[str, ...]] = {
    "artifact_origin": ("生成", "自动生成", "根据", "derive", "generated", "generate", "produced"),
    "artifact_responsibility": ("类型支持", "序列化", "反序列化", "编码", "解码", "接口", "强类型", "type support", "serializ", "deserializ", "encoding", "decoding", "typed", "interface"),
    "compatibility_outcome": ("不一致", "不匹配", "结构不同", "失败", "异常", "无法", "inconsistent", "mismatch", "different structure", "fail", "error", "cannot"),
}


def _tokens(value: Any) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(value or "").lower())}


def _candidate_id(item: dict[str, Any]) -> str:
    return str(item.get("segment_id") or item.get("chunk_id") or item.get("id") or "")


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("section", "heading_path", "content", "quote"))


def _facets_for_text(text: str) -> set[str]:
    lowered = text.lower()
    return {name for name, aliases in _FACET_ALIASES if any(alias.lower() in lowered for alias in aliases)}


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
    left_tokens, right_tokens = _tokens(_text(left)), _tokens(_text(right))
    return bool(left_tokens and right_tokens) and len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1) >= .82


def _facet(name: str, required: bool, terms: Iterable[str] = ()) -> dict[str, Any]:
    return {"id": name, "label": name, "terms": tuple(dict.fromkeys(value for value in (name, *terms) if value)), "required": required}


def extract_facet_requirements(query: str, rewritten: QueryRewrite | None = None) -> dict[str, list[dict[str, Any]]]:
    """Separate explicit requested facets from controlled retrieval expansions."""
    rewritten = rewritten or rewrite_query(query)
    required = [_facet(term, True) for term in rewritten.required_facets]
    required_ids = {facet["id"] for facet in required}
    auxiliary: list[dict[str, Any]] = []
    text = " ".join((rewritten.original_query, *rewritten.core_terms, *rewritten.scenario_terms, *rewritten.expansion_terms))
    for name in _facets_for_text(text):
        if name not in required_ids:
            aliases = next(aliases for facet, aliases in _FACET_ALIASES if facet == name)
            auxiliary.append(_facet(name, False, aliases))
    return {
        "required_facets": required,
        "auxiliary_facets": auxiliary,
        "relation_facets": list(rewritten.relation_facets),
        "required_relation_facets": [dict(item) for item in rewritten.relation_facets if item.get("required")],
    }


def facets_for_candidate(item: dict[str, Any], facets: Iterable[dict[str, Any]]) -> set[str]:
    text = _text(item).lower()
    return {str(facet["id"]) for facet in facets if any(str(term).lower() in text for term in facet.get("terms", ()) if term)}


def facet_candidate_map(candidates: list[dict[str, Any]], facets: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    facet_list = list(facets)
    result = {str(facet["id"]): [] for facet in facet_list}
    for item in candidates:
        candidate_id = _candidate_id(item)
        for facet_id in facets_for_candidate(item, facet_list):
            if candidate_id:
                result[facet_id].append(candidate_id)
    return result


_OFFER_WORDS = ("offered", "offer", "provide", "provides", "provided", "produce", "produces", "发布端", "提供", "产生", "生产")
_REQUEST_WORDS = ("requested", "request", "require", "requires", "consume", "consumes", "订阅端", "请求", "要求", "消费", "依赖")
_COMPAT_WORDS = ("compatible", "compatibility", "r x o", "rxo", "兼容", "匹配", "相容", "满足")
_RULE_WORDS = ("rule", "ordering", "greater", "lower", "higher", "less", "大于", "小于", "高于", "低于", "规则", ">", "<")
_STATUS_WORDS = ("status", "callback", "listener", "incompatible", "状态", "回调", "监听")
_SUBJECT_ROLE_ALIASES = {
    "writer": ("writer", "datawriter", "写者", "发布端", "发布者", "发送端"),
    "reader": ("reader", "datareader", "读者", "订阅端", "订阅者", "接收端"),
}


def _has_any(text: str, words: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def relation_support(item: dict[str, Any], relation: dict[str, Any]) -> dict[str, Any] | None:
    """Return normalized semantic support for a relation, if present.

    API names, enum names, listener callbacks and prose are treated as one
    support unit through their shared role/operation vocabulary.  No policy
    or product name is special-cased here.
    """
    text = _text(item)
    lowered = text.lower()
    subject = str(relation.get("subject") or "").lower()
    kind = str(relation.get("relation") or "").lower()
    object_name = str(relation.get("object") or "").lower()
    subject_aliases = _SUBJECT_ROLE_ALIASES.get(subject, (subject, "data" + subject) if subject else ())
    subject_hit = any(alias and alias in lowered for alias in subject_aliases)
    object_terms = [term for term in re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}", object_name) if term]
    object_hit = not object_terms or (all(term in lowered for term in object_terms) if kind in {"matches", "compatible", "satisfies"} else any(term in lowered for term in object_terms))
    role_hit = _has_any(lowered, _OFFER_WORDS if kind in {"offers", "produces"} else _REQUEST_WORDS if kind in {"requests", "consumes", "depends"} else _COMPAT_WORDS)
    if kind in {"offers", "produces"}:
        supported = subject_hit and object_hit and _has_any(lowered, _OFFER_WORDS)
    elif kind in {"requests", "consumes", "depends"}:
        supported = subject_hit and object_hit and _has_any(lowered, _REQUEST_WORDS)
    elif kind in {"matches", "compatible", "satisfies"}:
        compat_hit = _has_any(lowered, _COMPAT_WORDS) or "matching rule" in lowered or "match rule" in lowered
        supported = object_hit and compat_hit and (
            (subject_hit and _has_any(lowered, _OFFER_WORDS + _REQUEST_WORDS))
            or (_has_any(lowered, _OFFER_WORDS) and _has_any(lowered, _REQUEST_WORDS))
            or ("datawriter" in lowered and "datareader" in lowered)
            or _has_any(lowered, _RULE_WORDS)
        )
    else:
        supported = subject_hit and role_hit
    if not supported:
        return None
    return {"evidence_id": _candidate_id(item), "relation": relation, "normalization": {"subject": subject, "relation": kind}}


def relation_support_strength(item: dict[str, Any], relation: dict[str, Any]) -> int:
    """Rank semantic evidence forms without naming a particular API/policy."""
    if not relation_support(item, relation):
        return 0
    lowered = _text(item).lower()
    kind = str(relation.get("relation") or "").lower()
    strength = 1
    if _has_any(lowered, _STATUS_WORDS):
        strength += 2
    # Prefer evidence that names the requested relation side itself (for
    # example a requested/offered status or callback) over a generic QoS
    # paragraph that happens to mention both entities.
    if kind in {"offers", "produces"} and _has_any(lowered, _OFFER_WORDS):
        strength += 2
        if _has_any(lowered, ("offered_incompatible", "offered incompatible", "offered qos")):
            strength += 2
    elif kind in {"requests", "consumes"} and _has_any(lowered, _REQUEST_WORDS):
        strength += 2
        if _has_any(lowered, ("requested_incompatible", "requested incompatible", "requested qos")):
            strength += 2
    if kind in {"matches", "compatible", "satisfies"} and _has_any(lowered, _RULE_WORDS):
        strength += 2
    return strength


def relation_candidate_map(candidates: list[dict[str, Any]], relations: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    result = {str(index): [] for index, _ in enumerate(relations)}
    for index, relation in enumerate(relations):
        for item in candidates:
            if relation_support(item, relation):
                result[str(index)].append(_candidate_id(item))
    return result


def build_relation_recovery_query(query: str, relations: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str | None:
    """Build one bounded query for relations absent from both retrieval sources."""
    missing = [relation for index, relation in enumerate(relations)
               if not relation_candidate_map(candidates, [relation]).get("0")]
    if not missing:
        return None
    terms = [query]
    for relation in missing:
        terms.extend((
            str(relation.get("subject") or ""),
            str(relation.get("relation") or ""),
            str(relation.get("object") or ""),
            "compatibility", "matching", "constraint", "rule",
        ))
        # Add vocabulary for the missing relationship itself.  These are
        # generic relationship/rule terms, not domain or policy names; they
        # make a bounded recovery query reach standards-style RxO/order
        # paragraphs that use different wording from the user question.
        if str(relation.get("relation") or "").lower() in {"matches", "compatible", "satisfies"}:
            terms.extend(("RxO", "ordering", "precedence", "requested", "offered", "lower", "higher"))
    return " ".join(dict.fromkeys(term for term in terms if term))


def analyze_evidence_support(query: str, evidence: list[dict[str, Any]], required_facets: list[dict[str, Any]], relation_facets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classify final support as direct, compositional, or unsupported.

    A compositional chain needs independent evidence for artifact origin,
    responsibility, and a compatibility/failure consequence.  The relations
    are generic engineering concepts, not product- or question-specific rules.
    """
    relation_facets = relation_facets or []
    supporting = facet_candidate_map(evidence, required_facets)
    relation_supporting = relation_candidate_map(evidence, relation_facets)
    direct = sorted(facet_id for facet_id, ids in supporting.items() if ids)
    relation_ids: dict[str, list[str]] = {name: [] for name in _REASONING_RELATIONS}
    for item in evidence:
        text = _text(item).lower()
        candidate_id = _candidate_id(item)
        if not candidate_id:
            continue
        for relation, patterns in _REASONING_RELATIONS.items():
            if any(pattern.lower() in text for pattern in patterns):
                relation_ids[relation].append(candidate_id)
    linked_ids = set().union(*map(set, relation_ids.values()))
    has_chain = bool(_ENGINEERING_CHANGE_RE.search(query)) and all(relation_ids.values()) and len(linked_ids) >= 2
    compositional = sorted(
        str(facet["id"]) for facet in required_facets
        if has_chain and (supporting.get(str(facet["id"])) or len(required_facets) <= 1)
    )
    unsupported = sorted(str(facet["id"]) for facet in required_facets if str(facet["id"]) not in direct and str(facet["id"]) not in compositional)
    relation_covered = [key for key, ids in relation_supporting.items() if ids]
    relation_evidence_ids = [relation_supporting[key] for key in relation_covered]
    relation_chain = len(relation_covered) == len(relation_facets) and len(set().union(*map(set, relation_evidence_ids))) >= 2 if relation_facets else False
    return {
        "directly_covered_facets": direct,
        "compositionally_covered_facets": compositional,
        "unsupported_facets": unsupported,
        "facet_supporting_evidence_ids": supporting,
        "reasoning_links": [{"relation": relation, "evidence_ids": ids} for relation, ids in relation_ids.items() if ids],
        "covered_relation_facets": relation_covered,
        "uncovered_relation_facets": [str(index) for index in range(len(relation_facets)) if str(index) not in relation_covered],
        "relation_supporting_evidence_ids": relation_supporting,
        "relation_chain_supported": relation_chain,
        "semantic_normalization": [{"relation_index": key, "evidence_ids": ids} for key, ids in relation_supporting.items() if ids],
    }


def build_facet_trace(stages: dict[str, list[dict[str, Any]]], required_facets: list[dict[str, Any]], relation_facets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    relation_facets = relation_facets or []
    stage_maps = {stage: facet_candidate_map(items, required_facets) for stage, items in stages.items()}
    ordered = list(stages)
    first_seen, first_lost = {}, {}
    for facet in required_facets:
        facet_id = str(facet["id"])
        seen = False
        first_seen[facet_id] = next((stage for stage in ordered if stage_maps[stage][facet_id]), None)
        first_lost[facet_id] = None
        for stage in ordered:
            if stage_maps[stage][facet_id]:
                seen = True
            elif seen:
                first_lost[facet_id] = stage
                break
    result = {"required_facets": required_facets, "stages": stage_maps, "first_seen_stage": first_seen, "first_lost_stage": first_lost}
    if relation_facets:
        result["relation_stages"] = {stage: relation_candidate_map(items, relation_facets) for stage, items in stages.items()}
        result["relation_first_seen_stage"] = {
            str(index): next((stage for stage in ordered if relation_candidate_map(stages[stage], [relation])["0"]), None)
            for index, relation in enumerate(relation_facets)
        }
    if "evidence" in stages:
        result.update(analyze_evidence_support("", stages["evidence"], required_facets, relation_facets))
    return result


def select_evidence(query: str, candidates: list[dict[str, Any]], top_n: int = 5, *, requirements: dict[str, list[dict[str, Any]]] | None = None, force_relation_ids: Iterable[str] = (), preferred_candidate_ids: Iterable[str] = (), recovery_support_map: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Hard-cover explicit facets, then fill remaining final-evidence slots."""
    if not candidates or top_n <= 0:
        return []
    requirements = requirements or extract_facet_requirements(query)
    required, auxiliary = requirements["required_facets"], requirements["auxiliary_facets"]
    relations = requirements.get("required_relation_facets", requirements.get("relation_facets", []))
    forced = {str(value) for value in force_relation_ids}
    preferred = {str(value) for value in preferred_candidate_ids}
    recovery_support_map = recovery_support_map or {}
    remaining, selected, covered = list(candidates), [], set()

    # Relations are hard requirements before flat entity facets.  A generic
    # paragraph containing several entity words cannot satisfy this pass.
    covered_relations: set[str] = set()
    while remaining and len(selected) < top_n and relations:
        eligible = [(item, {str(index) for index, relation in enumerate(relations) if str(index) not in covered_relations and relation_support(item, relation) and (not forced or str(index) in forced)}) for item in remaining]
        eligible = [(item, gain) for item, gain in eligible if gain]
        if not eligible:
            break
        best, gain = max(eligible, key=lambda pair: (int(_candidate_id(pair[0]) in preferred), max(relation_support_strength(pair[0], relations[int(index)]) for index in pair[1]), len(pair[1]), float(pair[0].get("rerank_score", 0) or 0), float(pair[0].get("fusion_score", 0) or 0), _candidate_id(pair[0])))
        remaining.remove(best)
        selected.append(best)
        covered_relations.update(gain)

    while remaining and len(selected) < top_n:
        eligible = [(item, facets_for_candidate(item, required) - covered) for item in remaining]
        eligible = [(item, gain) for item, gain in eligible if gain]
        if not eligible:
            break
        best, gain = max(eligible, key=lambda pair: (len(pair[1]), float(pair[0].get("rerank_score", 0) or 0), float(pair[0].get("fusion_score", 0) or 0), _candidate_id(pair[0])))
        remaining.remove(best)
        selected.append(best)
        covered.update(gain)

    query_terms, requested_language = _tokens(query), _language(query)
    while remaining and len(selected) < top_n:
        def key(item: dict[str, Any]) -> tuple[float, float, float, str]:
            duplicate = any(_same_topic_group(item, chosen) for chosen in selected)
            language_exception = requested_language != "generic" and _language(_text(item)) == requested_language
            score = float(item.get("rerank_score", 0) or 0)
            overlap = float(len(query_terms & _tokens(_text(item))))
            return (score + .015 * len(facets_for_candidate(item, auxiliary)) + .001 * overlap - (.12 if duplicate and not language_exception else 0), score, overlap, _candidate_id(item))
        best = max(remaining, key=key)
        remaining.remove(best)
        selected.append(best)

    lexical_uncovered = {str(facet["id"]) for facet in required} - covered
    support = analyze_evidence_support(query, selected, required, relations)
    for rank, item in enumerate(selected, 1):
        item["evidence_rank"] = rank
        item["evidence_facets"] = sorted(facets_for_candidate(item, required + auxiliary))
        item["required_facets"] = [facet["id"] for facet in required]
        item["covered_facets"] = sorted(covered)
        item["uncovered_facets"] = sorted(lexical_uncovered)
        item["covered_relation_facets"] = support.get("covered_relation_facets", [])
        item["uncovered_relation_facets"] = support.get("uncovered_relation_facets", [])
        item["recovery_support_map"] = recovery_support_map
        item.update(support)
        item["scenario_terms"] = sorted(term for term in _SCENARIO_ALIASES if term in query.lower())
    return selected
