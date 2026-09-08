"""Conservative post-generation checks for high-risk DDS API claims."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reasons: tuple[str, ...] = ()


_INTERNAL_TERMS = ("内部锁", "锁顺序", "内部线程", "资源锁机制", "内部资源锁")


def validate_answer(answer: str, rerank_top5: list[dict], query: str = "") -> ValidationResult:
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

    return ValidationResult("answered" if not reasons else "insufficient_evidence", tuple(reasons))
