"""Conservative post-generation checks for high-risk DDS API claims."""

import re
from dataclasses import dataclass

from app.services.retrieval.evidence_service import analyze_evidence_support, relation_candidate_map


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reasons: tuple[str, ...] = ()
    missing_required_facets: tuple[str, ...] = ()
    negative_claim_facets: tuple[str, ...] = ()
    compositional_refusal_facets: tuple[str, ...] = ()
    missing_relations: tuple[str, ...] = ()
    missing_side_states: tuple[str, ...] = ()
    contradicted_negative_claims: tuple[str, ...] = ()

    @property
    def should_retry(self) -> bool:
        return bool(self.missing_required_facets or self.negative_claim_facets or self.compositional_refusal_facets)


_INTERNAL_TERMS = ("内部锁", "锁顺序", "内部线程", "资源锁机制", "内部资源锁")


def _facet_terms(facet: dict) -> tuple[str, ...]:
    return tuple(str(value) for value in facet.get("terms", ()) if value) or (str(facet.get("id") or ""),)


def _supports(item: dict, facet: dict) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("content", "quote", "section", "heading_path")).lower()
    return any(term.lower() in text for term in _facet_terms(facet) if term)


_NEGATIVE_CLAIM_RE = re.compile(
    r"(?:知识库|文档|资料|knowledge\s*base|documentation).{0,100}?(?:没有|未涉及|不包含|没有相关|无(?:法)?确定|no\s+(?:relevant\s+)?(?:definition|evidence|information)|not\s+(?:covered|available|contained)|does\s+not\s+contain)",
    re.I | re.S,
)
_COMPOSITIONAL_REFUSAL_RE = re.compile(
    r"(?:证据不足|未充分覆盖|无法(?:据此|确定|回答)|未说明|not enough evidence|insufficient evidence|cannot determine|not described|does not describe)",
    re.I,
)


def soften_unverified_negative_claims(answer: str) -> str:
    """Replace absolute KB-absence clauses after the one allowed retry.

    This is intentionally phrased in terms of final-evidence coverage.  It
    neither invents domain facts nor names any product-specific term.
    """
    sentence = re.compile(
        r"[^。！？.!?\n]*(?:知识库|文档|资料|knowledge\s*base|documentation)[^。！？.!?\n]*(?:没有|未涉及|不包含|无(?:法)?确定|no\s+(?:relevant\s+)?(?:definition|evidence|information)|not\s+(?:covered|available|contained)|does\s+not\s+contain)[^。！？.!?\n]*[。！？.!?]?",
        re.I,
    )
    softened = sentence.sub("当前最终证据未充分覆盖该方向，无法据此作出完整结论。", answer or "")
    marker = "当前最终证据未充分覆盖该方向，无法据此作出完整结论。"
    return marker.join(dict.fromkeys(part for part in softened.split(marker))) if softened.count(marker) > 1 else softened


def validate_answer(
    answer: str,
    rerank_top5: list[dict],
    query: str = "",
    *,
    candidate_pool: list[dict] | None = None,
    required_facets: list[dict] | None = None,
    relation_facets: list[dict] | None = None,
) -> ValidationResult:
    text = answer or ""
    evidence = "\n".join(str(item.get("content") or item.get("quote") or "") for item in rerank_top5)
    reasons: list[str] = []
    if not rerank_top5 or not evidence.strip():
        reasons.append("没有有效的 Rerank Top-5 证据")
    if query and evidence.strip():
        query_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}", query.lower()))
        evidence_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}", evidence.lower()))
        if query_terms and not (query_terms & evidence_terms):
            reasons.append("Top-5 证据与原问题缺少可验证的主题重合")

    loan_claim = re.search(
        r"return[_ ]?loan\s*\(?.{0,50}(改变|修改|设置|负责).{0,30}(sample.?state|样本状态|READ)",
        text, re.I | re.S,
    )
    loan_denial = re.search(
        r"return[_ ]?loan\s*\(?.{0,30}(不改变|不会改变|不是.*负责|不负责).{0,20}(sample.?state|样本状态|READ)",
        text, re.I | re.S,
    )
    if loan_claim and not loan_denial:
        reasons.append("return_loan 被解释为负责改变 SampleState")

    if re.search(r"take[_ ]?next[_ ]?sample.{0,60}(take\(\)|普通 take|所有 take|take 方法).{0,40}(未读|只读未读)", text, re.I | re.S):
        reasons.append("take_next_sample 的未读语义被推广到普通 take")

    if re.search(r"\bread\s*(?:\(\))?.{0,35}(移除|删除|取出).{0,25}(样本|数据)", text, re.I | re.S):
        reasons.append("read 被解释为移除 DataReader 中的样本")
    if re.search(r"\btake\s*(?:\(\))?.{0,35}(保留|不移除|不删除).{0,25}(样本|数据)", text, re.I | re.S):
        reasons.append("take 被解释为保留 DataReader 中的样本")

    for term in _INTERNAL_TERMS:
        if term in text and term not in evidence:
            reasons.append(f"回答补充了证据未覆盖的内部实现：{term}")
            break

    required_facets = required_facets or []
    candidate_pool = candidate_pool or rerank_top5
    relation_facets = relation_facets or []
    support = analyze_evidence_support(query, rerank_top5, required_facets, relation_facets)
    compositionally_covered = set(support["compositionally_covered_facets"])
    missing: list[str] = []
    negative: list[str] = []
    compositional_refusal: list[str] = []
    pool_relation_support = relation_candidate_map(candidate_pool, relation_facets)
    final_relation_support = relation_candidate_map(rerank_top5, relation_facets)
    missing_relations = [key for key, ids in pool_relation_support.items() if ids and not final_relation_support.get(key)]
    negative_windows = [
        sentence.lower() for sentence in re.split(r"(?<=[。！？.!?])|\n+", text)
        if _NEGATIVE_CLAIM_RE.search(sentence)
    ]
    for facet in required_facets:
        facet_id = str(facet.get("id") or "")
        if not facet_id:
            continue
        pool_supports = any(_supports(item, facet) for item in candidate_pool)
        final_supports = any(_supports(item, facet) for item in rerank_top5)
        answer_mentions = any(term.lower() in text.lower() for term in _facet_terms(facet))
        if pool_supports and not final_supports and facet_id not in compositionally_covered:
            missing.append(facet_id)
        if pool_supports and facet_id not in compositionally_covered and any(any(term.lower() in window for term in _facet_terms(facet)) for window in negative_windows):
            negative.append(facet_id)
        elif pool_supports and facet_id not in compositionally_covered and not answer_mentions:
            # The final answer omits a user-explicit direction despite a
            # candidate pool that can support it.
            missing.append(facet_id)
    if missing:
        reasons.append("最终证据/回答未覆盖已召回的 required facets: " + ", ".join(dict.fromkeys(missing)))
    if negative:
        reasons.append("回答对已有候选证据的 facet 作出了绝对不存在声明: " + ", ".join(dict.fromkeys(negative)))
    if missing_relations:
        reasons.append("最终证据未覆盖已召回的 required relations: " + ", ".join(missing_relations))
        missing.extend("relation:" + key for key in missing_relations)
    relation_chain = bool(support.get("relation_chain_supported"))
    if relation_chain and _COMPOSITIONAL_REFUSAL_RE.search(text):
        negative.extend("relation:" + key for key in support.get("covered_relation_facets", []))
        reasons.append("回答忽略了已覆盖的关系证据链并以缺少场景原句拒答")
    if compositionally_covered and _COMPOSITIONAL_REFUSAL_RE.search(text):
        compositional_refusal = sorted(compositionally_covered)
        reasons.append("回答忽略了可组合证据链并以缺少场景原句拒答: " + ", ".join(compositional_refusal))
    missing_relation_values = tuple(dict.fromkeys("relation:" + key for key in missing_relations))
    contradicted = tuple(dict.fromkeys(negative))
    return ValidationResult(
        "answered" if not reasons else "insufficient_evidence",
        tuple(reasons),
        tuple(dict.fromkeys(missing)),
        contradicted,
        tuple(compositional_refusal),
        missing_relation_values,
        tuple(facet for facet in missing if not str(facet).startswith("relation:")),
        tuple(dict.fromkeys(negative)),
    )
