"""Conservative post-generation checks for high-risk DDS API claims."""

import re
from dataclasses import dataclass

from app.services.retrieval.evidence_service import (
    analyze_evidence_support,
    action_applicability_conflicts,
    concept_identities,
    facets_for_candidate,
    relation_candidate_map,
    relation_constraint_candidate_map,
    relation_requires_constraint,
    semantic_concept_conflicts,
    facet_concept_identity,
)


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reasons: tuple[str, ...] = ()
    missing_required_facets: tuple[str, ...] = ()
    negative_claim_facets: tuple[str, ...] = ()
    compositional_refusal_facets: tuple[str, ...] = ()
    missing_relations: tuple[str, ...] = ()
    missing_relation_constraints: tuple[str, ...] = ()
    missing_side_states: tuple[str, ...] = ()
    contradicted_negative_claims: tuple[str, ...] = ()
    ignored_missing_facets: tuple[str, ...] = ()
    raw_llm_negative_claims: tuple[str, ...] = ()
    negative_claim_conflicts_with_coverage: tuple[str, ...] = ()
    generation_evidence_conflict: bool = False
    unsupported_claims: tuple[str, ...] = ()
    evidence_strength: dict = None
    overclaim_detected: bool = False
    overclaim_claims: tuple[str, ...] = ()
    exact_api_conflicts: tuple[str, ...] = ()
    semantic_concept_conflicts: tuple[str, ...] = ()
    action_applicability_conflicts: tuple[str, ...] = ()
    supported_claims: tuple[str, ...] = ()
    causal_overclaim_claims: tuple[str, ...] = ()
    lifecycle_state_conflicts: tuple[str, ...] = ()
    numeric_unit_conflicts: tuple[str, ...] = ()
    return_code_conflicts: tuple[str, ...] = ()
    mechanism_conflicts: tuple[str, ...] = ()
    answer_covered_facets: tuple[str, ...] = ()
    answer_missing_facets: tuple[str, ...] = ()
    answer_facet_snippets: dict = None
    output_integrity_issues: tuple[str, ...] = ()
    parameter_name_conflicts: tuple[str, ...] = ()

    @property
    def should_retry(self) -> bool:
        return bool(
            self.missing_required_facets
            or self.negative_claim_facets
            or self.compositional_refusal_facets
            or self.missing_relations
            or self.missing_relation_constraints
            or self.missing_side_states
            or self.negative_claim_conflicts_with_coverage
            or self.unsupported_claims
            or self.overclaim_detected
            or self.exact_api_conflicts
            or self.semantic_concept_conflicts
            or self.action_applicability_conflicts
            or self.causal_overclaim_claims
            or self.lifecycle_state_conflicts
            or self.numeric_unit_conflicts
            or self.return_code_conflicts
            or self.mechanism_conflicts
            or self.output_integrity_issues
            or self.parameter_name_conflicts
        )


_INTERNAL_TERMS = ("内部锁", "锁顺序", "内部线程", "资源锁机制", "内部资源锁")
_UNSUPPORTED_MECHANISM_RE = re.compile(
    r"协议本身.{0,40}(?:处理|完成|负责|转换)|"
    r"(?:报文头部|报文布局|数据的初始排列|内部编码|运行时实现|自动(?:完成)?转换)|"
    r"(?:protocol itself|packet header|packet layout|initial (?:byte|data) order|"
    r"internal encoding|runtime implementation|automatic byte[- ]order conversion)",
    re.I,
)


def _facet_terms(facet: dict) -> tuple[str, ...]:
    terms = [str(value) for value in facet.get("terms", ()) if value]
    identity = facet_concept_identity(facet)
    identity_aliases = {
        "entity_lifecycle": ("entity lifecycle", "实体生命周期", "实体创建", "实体删除", "父子实体"),
        "reader_data_lifecycle": ("reader data lifecycle", "ReaderDataLifecycle", "读者数据生命周期"),
        "qos_mutability": ("immutable qos", "immutable policy", "不可变 QoS", "不可变QoS", "使能后不可修改"),
    }
    terms.extend(identity_aliases.get(identity or "", ()))
    return tuple(dict.fromkeys(terms)) or (str(facet.get("id") or ""),)


def _answer_term_matches(text: str, term: str) -> bool:
    """Match an explicit answer label without broad substring matching."""
    lowered = str(text or "").casefold()
    candidate = str(term or "").strip().casefold()
    if not candidate:
        return False
    if candidate in lowered:
        return True
    if not re.fullmatch(r"[a-z][a-z0-9_.+\- ]*", candidate):
        return False
    canonical = re.sub(r"[^a-z0-9]", "", candidate)
    for token in re.findall(r"[a-z][a-z0-9_.+\-_]*", lowered):
        if re.search(r"[_\-\s]", token) and re.sub(r"[^a-z0-9]", "", token) == canonical:
            return True
    return False


def _answer_blocks(answer: str) -> list[str]:
    """Split prose, lists, headings, and table rows into answer blocks."""
    text = str(answer or "").replace("\r\n", "\n")
    blocks = re.split(
        r"\n\s*(?=(?:[-*+]|\d+[.)]|#{1,6}\s|\|))|\n\s*\n+",
        text,
        flags=re.M,
    )
    return [re.sub(r"\s+", " ", block).strip() for block in blocks if block.strip()]


def _answer_coverage_blocks(answer: str) -> list[str]:
    """Keep a Markdown heading together with the bullets it introduces."""
    text = str(answer or "").replace("\r\n", "\n")
    if re.search(r"(?m)^\s*#{1,6}\s", text):
        sections = re.split(r"\n\s*(?=#{1,6}\s)", text)
        return [re.sub(r"\s+", " ", section).strip() for section in sections if section.strip()]
    return _answer_blocks(text)


_FACET_EXPLANATION_RE = re.compile(
    r"用于|表示|指的是|作用|负责|包含|包括|对应|监听|发送|接收|绑定|匹配|"
    r"检查|核对|确认|验证|查看|排查|判断|依据|现象|原因|不可达|可达|通信|"
    r"\b(?:is|means?|used|serves?|contains?|includes?|represents?|controls?|"
    r"carries?|sends?|receives?|binds?|listens?|matches?|check|verify|inspect|"
    r"validate|diagnose|symptom|evidence|address|reachable|unreachable)\b",
    re.I,
)


def _facet_block_has_explanation(
    block: str,
    terms: tuple[str, ...],
    active_facets: tuple[dict, ...] = (),
) -> bool:
    """Reject a facet label that has no independently useful statement."""
    normalized = re.sub(r"[*_`#]", "", str(block or ""))
    heading_label = bool(re.match(r"^\s*#{1,6}", str(block or ""))) and any(
        _answer_term_matches(normalized, str(term)) for term in terms if term
    )
    active_matches = {
        str(active_facet.get("id") or "").casefold()
        for active_facet in active_facets
        if any(
            term and _answer_term_matches(normalized, str(term))
            for term in _facet_terms(active_facet)
        )
    }
    label_match = heading_label or any(
        re.search(
            rf"^\s*(?:[-*+]|\d+[.)])?\s*{re.escape(str(term))}\s*[:：—-]",
            normalized,
            flags=re.I,
        )
        for term in terms if term
    )
    # A paragraph that merely lists several required names and then gives one
    # shared action is not an independent answer block for any one facet. A
    # labeled row is allowed because its RHS is the facet-local block.
    if len(active_matches) > 1 and not label_match:
        return False
    if heading_label:
        normalized = re.sub(r"^\s*#{1,6}\s*(?:\d+[.)]\s*)?", "", normalized, count=1)
    if label_match:
        if re.search(r"[:：—-]", normalized):
            normalized = re.split(r"[:：—-]", normalized, maxsplit=1)[1]
    for term in sorted((str(value) for value in terms if value), key=len, reverse=True):
        normalized = re.sub(re.escape(term), " ", normalized, flags=re.I)
    normalized = re.sub(r"\[[^\]]+\]|（证据[^）]+）|\(evidence[^)]+\)", " ", normalized, flags=re.I)
    normalized = re.sub(r"^\s*(?:[-*+]|\d+[.)])?\s*[:：—-]?\s*", "", normalized).strip()
    if not normalized:
        return False
    if _FACET_EXPLANATION_RE.search(normalized):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*", normalized)
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    return len(words) >= 3 or len(chinese) >= 6


def _answer_facet_coverage(
    answer: str,
    query: str,
    required_facets: list[dict],
    supported_facets: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, str]]:
    """Return coverage only when a supported facet has a real answer block."""
    blocks = _answer_coverage_blocks(answer)
    covered: list[str] = []
    missing: list[str] = []
    snippets: dict[str, str] = {}
    supported = {str(value) for value in supported_facets}
    if not _is_diagnostic_query(query):
        covered = [
            str(facet.get("id") or "") for facet in required_facets
            if str(facet.get("id") or "") in supported
        ]
        return tuple(dict.fromkeys(covered)), (), snippets
    active = [facet for facet in required_facets if str(facet.get("id") or "") in supported]
    all_active_terms = tuple(
        term for other in active for term in _facet_terms(other)
    )
    for facet in active:
        facet_id = str(facet.get("id") or "")
        terms = _facet_terms(facet)
        matching = [
            block for block in blocks
            if any(_answer_term_matches(block, term) for term in terms)
        ]
        snippets[facet_id] = matching[0] if matching else ""
        dedicated = False
        for block in matching:
            normalized = re.sub(r"[*_`#]", "", block)
            labeled = any(
                re.search(
                    rf"^\s*(?:[-*+]|\d+[.)])?\s*{re.escape(str(term))}\s*[:：—-]",
                    normalized,
                    flags=re.I,
                )
                for term in terms if term
            )
            if _facet_block_has_explanation(
                block,
                tuple(dict.fromkeys((*terms, *all_active_terms))),
                tuple(active),
            ):
                dedicated = True
                snippets[facet_id] = block
                break
        if dedicated:
            covered.append(facet_id)
        else:
            missing.append(facet_id)
    return tuple(dict.fromkeys(covered)), tuple(dict.fromkeys(missing)), snippets


def _output_integrity_issues(answer: str) -> list[str]:
    """Detect truncation/duplication before a result can be considered valid."""
    text = str(answer or "").strip()
    if not text:
        return ["empty_answer"]
    issues: list[str] = []
    if text.count("```") % 2:
        issues.append("unclosed_code_fence")
    if text.count("`") % 2:
        issues.append("unclosed_inline_code")
    for left, right, name in (("(", ")", "parentheses"), ("[", "]", "brackets"), ("{", "}", "braces")):
        if text.count(left) != text.count(right):
            issues.append(f"unbalanced_{name}")
    if re.search(r"(?:[:：,，、]|->|=>|\b(?:and|or|with|to|for)\b)\s*$", text, re.I):
        issues.append("trailing_fragment")
    if re.search(r"(?:检查|确认|验证|配置|设置|查看|排查)\s+[A-Za-z][A-Za-z0-9_.-]*\.$", text, re.I):
        issues.append("truncated_parameter_sentence")
    sentences = _answer_sentences(text)
    claim_sentences = []
    for value in sentences:
        # _answer_sentences deliberately handles ordinary prose and Markdown
        # with one splitter.  A citation such as "guide.pdf - 2.2.3." is
        # therefore broken into several short units; those units are layout
        # metadata, not repeated claims.  Only compare substantive units so a
        # valid answer with repeated source labels or list markers is not
        # rejected as a duplicate.
        normalized_value = re.sub(r"[*_`#]", "", value).strip()
        if re.search(r"(?:来源|source)", normalized_value, re.I):
            continue
        if re.match(r"(?:pdf|docx?|manual|guide)\s*-\s*\d", normalized_value, re.I):
            continue
        if normalized_value.endswith(")*"):
            continue
        if normalized_value.endswith(")") and re.search(r"\bZRDDS\b", normalized_value, re.I):
            continue
        if normalized_value.endswith(")") and re.search(r"(?:QosPolicy|UserManual|故障排查指南|用户手册)", normalized_value, re.I):
            continue
        if re.search(r";\s*(?:ZRDDS|pdf|manual|guide)", normalized_value, re.I):
            continue
        if re.search(r"(?:\[证据|\[evidence|解决方法|source)", normalized_value, re.I) and len(normalized_value) < 100:
            continue
        if re.fullmatch(r"(?:\d+[.)]?|[.])", normalized_value):
            continue
        if re.fullmatch(r"[A-Za-z一-鿿 ._-]+\s+-\s+\d+\.", normalized_value):
            continue
        if re.fullmatch(r"[^:：]{1,60}[:：]\s*", normalized_value):
            continue
        # Ignore punctuation/number-only citation fragments and headings that
        # were split at a filename or section number.
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", normalized_value):
            continue
        if len(normalized_value) < 8:
            continue
        claim_sentences.append(value)
    normalized = [re.sub(r"\s+", " ", value).casefold() for value in claim_sentences]
    if len(normalized) != len(set(normalized)):
        issues.append("duplicated_claim")
    nonempty_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    if len(nonempty_lines) >= 2 and nonempty_lines[0] == nonempty_lines[1]:
        issues.append("duplicated_opening")
    return list(dict.fromkeys(issues))


_PARAMETER_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z][A-Za-z0-9_]*\.)+[A-Za-z][A-Za-z0-9_]*(?![A-Za-z0-9_])"
)


def _parameter_name_conflicts(answer: str, evidence: str, query: str) -> list[str]:
    allowed = {
        value.casefold()
        for value in _PARAMETER_NAME_RE.findall(f"{evidence}\n{query}")
    }
    return list(dict.fromkeys(
        value for value in _PARAMETER_NAME_RE.findall(answer or "")
        if value.casefold() not in allowed
    ))


def _is_diagnostic_query(query: str) -> bool:
    """Identify troubleshooting requests without classifying all comparisons as diagnostic."""
    return bool(re.search(
        r"排查|定位|诊断|故障|异常|错误|日志|抓包|问题|如何.*(检查|验证)|"
        r"troubleshoot|diagnos|debug|investigat|symptom|log|packet\s+capture|"
        r"how\s+to\s+(check|verify|find|identify)",
        str(query or ""),
        re.I,
    ))


def _supports(item: dict, facet: dict) -> bool:
    # Match the selector's concept-aware coverage.  Lexical matching would
    # treat Entity Lifecycle and ReaderDataLifecycle as interchangeable.
    return str(facet.get("id") or "") in facets_for_candidate(item, [facet])


_NEGATIVE_CLAIM_RE = re.compile(
    r"(?:知识库|文档|资料|knowledge\s*base|documentation).{0,100}?(?:没有|未涉及|不包含|没有相关|无(?:法)?确定|no\s+(?:relevant\s+)?(?:definition|evidence|information)|not\s+(?:covered|available|contained)|does\s+not\s+(?:contain|provide))",
    re.I | re.S,
)
_COMPOSITIONAL_REFUSAL_RE = re.compile(
    r"(?:证据不足|未充分覆盖|无法(?:据此|确定|回答)|未说明|not enough evidence|insufficient evidence|cannot determine|not described|does not describe)",
    re.I,
)
_RAW_NEGATIVE_CLAIM_RE = re.compile(
    r"(?:知识库|文档|资料|证据|当前(?:最终)?证据|knowledge\s*base|documentation|evidence).{0,120}?"
    r"(?:没有|未提供|未涉及|未说明|不包含|不足|未充分覆盖|无法(?:判断|确定|回答)|"
    r"证据不足|no\s+(?:relevant\s+)?(?:definition|evidence|information)|"
    r"not\s+(?:covered|available|contained|provided|provide)|cannot\s+(?:determine|answer|be\s+determined)|"
    r"insufficient\s+evidence)",
    re.I | re.S,
)
_STANDALONE_NEGATIVE_CLAIM_RE = re.compile(
    r"(?:证据不足|无法(?:判断|确定|回答)|cannot\s+(?:determine|answer|be\s+determined)|insufficient\s+evidence)",
    re.I,
)
_CONSTRAINT_NEGATIVE_TARGET_RE = re.compile(
    r"(?:rule|ordering|comparison|constraint|compatib|greater|less|higher|lower|"
    r"规则|顺序|比较|约束|兼容|大于|小于|高于|低于)",
    re.I,
)

_TECHNICAL_TOKEN_RE = re.compile(
    r"\b(?:[A-Z]{2,}[A-Z0-9_]*|[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+|"
    r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)\b"
)
_NUMERIC_DETAIL_RE = re.compile(
    r"(?<![\w])\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|KiB|MiB|GiB|秒|毫秒|微秒|ms|us|ns|s|kb|mb|gb|字节|bytes?)\b",
    re.I,
)
# Logical prose tokens are not technical entities.  Treating uppercase AND/OR
# as acronyms makes otherwise evidence-grounded logical explanations fail the
# unsupported-entity guard.
_NON_CLAIM_TOKENS = {"AI", "LLM", "HTTP", "URL", "JSON", "API", "DDS", "RTPS", "AND", "OR"}
_ABSOLUTE_CLAIM_RE = re.compile(
    r"\u5fc5\u7136|\u4e00\u5b9a|\u53ea\u6709|\u5c31\u662f|\u76f4\u63a5\u8bc1\u660e|\u552f\u4e00(?:\u539f\u56e0|\u6839\u56e0)?|100\s*%|\u4fdd\u8bc1|\u901a\u5e38\u610f\u5473|\u65e0\u6cd5\u901a\u4fe1|\u4f1a\u5931\u8d25|usually\s+means|will\s+fail|cannot\s+communicate|"
    r"\u4e00\u5b9a(?:\u63d0\u5347|\u964d\u4f4e|\u8bf4\u660e)|"
    r"\b(?:always|must|guarantee(?:d)?|唯一|only|proves?|certainly|100\s*%)\b",
    re.I,
)
_INFERENCE_MARKER_RE = re.compile(
    r"可能|更值得优先检查|可以将范围缩小到|需要进一步验证|建议先|候选|风险|perhaps|may|might|likely|prioritize|candidate|needs? verification",
    re.I,
)
_EXACT_API_SEMANTIC_RE = re.compile(
    r"SampleState|ViewState|InstanceState|状态掩码|state\s*mask|未读|样本状态|样本|sample|"
    r"移除|保留|归还|返回|loan|remove|keep|return|掩码|parameter|参数",
    re.I,
)
_DIRECT_STRENGTH_RE = re.compile(
    r"直接|表示|定义|会将|保留|移除|返回|调用|参数为|means?|returns?|removes?|keeps?|copies?|is defined",
    re.I,
)
_CAUSAL_LINK_RE = re.compile(
    r"因此|所以|导致|进而|说明|就是|必然|直接导致|因而|therefore|thus|"
    r"causes?|leads?\s+to|results?\s+in|hence|proves?",
    re.I,
)
_QUALIFIED_DIAGNOSTIC_RE = re.compile(
    r"可能|候选|优先检查|需要(?:进一步)?验证|不能(?:直接|单独)|不等于|取决于|"
    r"may|might|possible|candidate|verify|check|cannot\s+(?:directly|alone)",
    re.I,
)
_LIFECYCLE_ENABLED_RE = re.compile(
    r"(?:实体|qos|policy|策略).{0,60}(?:使能后|启用后|enabled)|"
    r"(?:after|once|when)\s+(?:(?:the|a|an)\s+)?(?:entity\s+)?(?:is\s+)?enabled",
    re.I,
)
_LIFECYCLE_CREATED_RE = re.compile(
    r"(?:实体|qos|policy|策略).{0,60}(?:创建后|创建时不能|创建前)|"
    r"(?:创建后(?:不能|不可|无法)|创建前(?:必须|需要|修改))|"
    r"(?:after|once)\s+(?:the\s+)?(?:entity\s+)?creation|"
    r"before\s+(?:the\s+)?(?:entity\s+)?(?:is\s+)?created",
    re.I,
)
_WEAK_FAILURE_RE = re.compile(
    r"可能(?:失败|被忽略|不生效)|可能会失败|may\s+(?:fail|be ignored|not take effect)|"
    r"could\s+(?:fail|be ignored)|possibly\s+ignored",
    re.I,
)
_MECHANISM_ASSERTION_RE = re.compile(
    r"\u8bf4\u660e|\u610f\u5473|\u7b49\u4e8e|\u7b49\u540c|\u4ee3\u8868|\u8bc1\u660e|\u5bfc\u81f4|\u56e0\u6b64|\u5c31\u662f|means?|equals?|equivalent|therefore|thus|hence|"
    r"indicates?|proves?|causes?|leads?\s+to|results?\s+in",
    re.I,
)
_MECHANISM_NEGATION_RE = re.compile(
    r"\u4e0d\u7b49\u4e8e|\u4e0d\u7b49\u540c|\u4e0d\u662f|\u4e0d\u80fd\u4ec5\u51ed|\u4e0d\u80fd\u8bf4\u660e|\u4e0d\u4ee3\u8868|\u4e0d\u80fd\u636e\u6b64|\u5e76\u975e|"
    r"not\s+(?:equal|equivalent)|does\s+not\s+mean|cannot\s+(?:alone|by itself)|"
    r"not\s+proof",
    re.I,
)


def _mechanism_conflicts(answer: str, evidence: str) -> list[str]:
    """Keep QoS, discovery, type/serialization, and network mechanisms distinct."""
    evidence_sentences = _answer_sentences(evidence)
    pairs = (
        ("qos_incompatible!=type_incompatible", r"qos|\u670d\u52a1\u8d28\u91cf|\u4e0d\u517c\u5bb9|incompatib", r"idl|type|\u7c7b\u578b|\u5e8f\u5217\u5316|\u53cd\u5e8f\u5217\u5316|deserial"),
        ("matched!=deserialization_success", r"matched|match|\u5339\u914d|discovery|\u53d1\u73b0", r"deserialize|deserial|\u53cd\u5e8f\u5217\u5316|\u5e8f\u5217\u5316|idl|type|\u7c7b\u578b"),
        ("network!=type_incompatible", r"network|\u7f51\u7edc|nic|\u7f51\u5361|ip|\u5730\u5740|\u7aef\u53e3|\u4e0d\u53ef\u8fbe", r"idl|type|\u7c7b\u578b|\u5e8f\u5217\u5316|\u53cd\u5e8f\u5217\u5316|deserial"),
    )
    conflicts: list[str] = []
    for sentence in _answer_sentences(answer):
        if not _MECHANISM_ASSERTION_RE.search(sentence) or _MECHANISM_NEGATION_RE.search(sentence):
            continue
        for label, left, right in pairs:
            if not re.search(left, sentence, re.I) or not re.search(right, sentence, re.I):
                continue
            direct_evidence = any(
                re.search(left, item, re.I)
                and re.search(right, item, re.I)
                and _MECHANISM_ASSERTION_RE.search(item)
                and not _MECHANISM_NEGATION_RE.search(item)
                and not re.search(
                    r"separate|distinct|independent|requires?\s+(?:a\s+)?separate|"
                    r"\u5206\u522b|\u5206\u5f00|\u72ec\u7acb|\u4e0d\u540c|\u5404\u81ea|\u4ec5\u8868\u793a",
                    item,
                    re.I,
                )
                for item in evidence_sentences
            )
            if not direct_evidence:
                conflicts.append(f"{label}:{sentence}")
    return list(dict.fromkeys(conflicts))


def _lifecycle_state_conflicts(answer: str, evidence: str) -> list[str]:
    """Reject a created-state claim when Evidence only fixes enabled-state."""
    if not _LIFECYCLE_CREATED_RE.search(answer or ""):
        return []
    if _LIFECYCLE_ENABLED_RE.search(evidence or "") and not _LIFECYCLE_CREATED_RE.search(evidence or ""):
        return ["enabled!=created"]
    return []


def _explicit_return_code_conflicts(answer: str, evidence: str) -> list[str]:
    """Keep explicit documented return codes from being weakened."""
    conflicts: list[str] = []
    answer_text = answer or ""
    evidence_text = evidence or ""
    for code, label in (
        ("DDS_RETCODE_IMMUTABLE_POLICY", "IMMUTABLE_POLICY"),
        ("DDS_RETCODE_INCONSISTENT", "INCONSISTENT"),
    ):
        if code in evidence_text and _WEAK_FAILURE_RE.search(answer_text) and label not in answer_text:
            conflicts.append(f"{code}:weakened")
    return conflicts


def _causal_overclaim_conflicts(answer: str, evidence: str) -> list[str]:
    """Detect known unsafe causal upgrades while retaining qualified advice."""
    evidence_text = evidence or ""
    conflicts: list[str] = []
    for sentence in _answer_sentences(answer):
        lowered = sentence.lower()
        if not _CAUSAL_LINK_RE.search(sentence) or _QUALIFIED_DIAGNOSTIC_RE.search(sentence):
            continue
        risky_pairs = (
            ("history", "sample_rejected", "history->sample_rejected"),
            ("read", "ack", "application_read->ack"),
            ("read", "nack", "application_read->nack"),
        )
        for left, right, label in risky_pairs:
            if left in lowered and right in lowered:
                direct = re.search(
                    rf"{re.escape(left)}.{{0,100}}(?:therefore|thus|导致|因而|caus|leads?\s+to).{{0,100}}{re.escape(right)}|"
                    rf"{re.escape(right)}.{{0,100}}(?:therefore|thus|导致|因而|caus|leads?\s+to).{{0,100}}{re.escape(left)}",
                    evidence_text,
                    re.I | re.S,
                )
                if not direct:
                    conflicts.append(sentence)
        if re.search(r"reliable", lowered) and re.search(r"绝不丢|零丢|不丢失|never\s+lose|zero\s+loss|guarantee", lowered, re.I):
            conflicts.append(sentence)
        if re.search(r"best[_ -]?effort", lowered) and re.search(r"就是\s*udp|等于\s*udp|is\s+udp|equals?\s+udp", lowered, re.I):
            if not re.search(r"best[_ -]?effort.{0,100}udp|udp.{0,100}best[_ -]?effort", evidence_text, re.I | re.S):
                conflicts.append(sentence)
    return list(dict.fromkeys(conflicts))


def _extract_raw_negative_claims(answer: str) -> list[str]:
    claims = []
    for sentence in re.split(r"(?<=[。！？.!?])|\n+", answer or ""):
        sentence = sentence.strip()
        if sentence and (_RAW_NEGATIVE_CLAIM_RE.search(sentence) or _STANDALONE_NEGATIVE_CLAIM_RE.search(sentence)):
            claims.append(sentence)
    return list(dict.fromkeys(claims))


def _claim_strengths(answer: str, evidence: str) -> tuple[dict[str, str], list[str]]:
    """Classify generated sentences without pretending to prove semantics.

    Direct facts must have a grounded technical anchor and a direct wording
    signal.  Inference wording is permitted, while absolute wording without a
    matching strong statement in evidence is an overclaim.  Everything else
    remains unsupported and is handled by the existing claim filter.
    """
    strengths: dict[str, str] = {}
    overclaims: list[str] = []
    evidence_lower = evidence.casefold()
    for sentence in [part.strip() for part in re.split(r"(?<=[。！？.!?])|\n+", answer or "") if part.strip()]:
        technical = [token for token in _TECHNICAL_TOKEN_RE.findall(sentence) if token not in _NON_CLAIM_TOKENS]
        grounded = not technical or all(token.casefold() in evidence_lower for token in technical)
        absolute = bool(_ABSOLUTE_CLAIM_RE.search(sentence))
        inference = bool(_INFERENCE_MARKER_RE.search(sentence))
        direct = bool(_DIRECT_STRENGTH_RE.search(sentence)) and (not technical or grounded)
        if absolute and not inference:
            evidence_has_strong = bool(_ABSOLUTE_CLAIM_RE.search(evidence) or re.search(r"\b(?:must|always|shall)\b|必然|一定|保证", evidence, re.I))
            if not evidence_has_strong:
                overclaims.append(sentence)
                strengths[sentence] = "unsupported"
                continue
        if not grounded:
            strengths[sentence] = "unsupported"
        elif inference:
            strengths[sentence] = "supported_inference"
        elif direct:
            strengths[sentence] = "direct_fact"
        else:
            strengths[sentence] = "supported_inference" if grounded else "unsupported"
    return strengths, list(dict.fromkeys(overclaims))


def _exact_api_conflicts(answer: str, evidence_items: list[dict], required_facets: list[dict]) -> list[str]:
    """Prevent a related API family from supplying exact API semantics."""
    evidence_concepts = set().union(*(concept_identities(" ".join(str(item.get(k) or "") for k in ("content", "quote", "section"))) for item in evidence_items)) if evidence_items else set()
    answer_lower = (answer or "").lower()
    conflicts: list[str] = []
    for facet in required_facets:
        identity = facet_concept_identity(facet) or ""
        if not identity.startswith("exact_api:"):
            continue
        api_name = identity.split(":", 1)[1]
        api_aliases = {
            "read_next_sample": ("read_next_sample", "read next sample"),
            "take_next_sample": ("take_next_sample", "take next sample"),
            "return_loan": ("return_loan", "return loan"),
            "read": ("read()", "read 方法", "read method"),
            "take": ("take()", "take 方法", "take method"),
        }.get(api_name, (api_name,))
        answer_mentions = any(alias in answer_lower for alias in api_aliases)
        if not answer_mentions or not _EXACT_API_SEMANTIC_RE.search(answer):
            continue
        direct_exact = False
        for item in evidence_items:
            item_text = " ".join(str(item.get(k) or "") for k in ("content", "quote", "section"))
            for alias in api_aliases:
                for match in re.finditer(re.escape(alias), item_text, re.I):
                    window = item_text[max(0, match.start() - 180):match.end() + 260]
                    if _EXACT_API_SEMANTIC_RE.search(window):
                        direct_exact = True
                        break
                if direct_exact:
                    break
            if direct_exact:
                break
        if direct_exact:
            continue
        related = sorted(value for value in evidence_concepts if value.startswith("exact_api:") and value != identity)
        if related and (api_name in answer_lower or _EXACT_API_SEMANTIC_RE.search(answer)):
            conflicts.append(f"{identity}:{','.join(related)}")
        elif not related:
            conflicts.append(f"{identity}:no_exact_evidence")
    return conflicts


def soften_unverified_negative_claims(answer: str) -> str:
    """Replace absolute KB-absence clauses after the one allowed retry.

    This is intentionally phrased in terms of final-evidence coverage.  It
    neither invents domain facts nor names any product-specific term.
    """
    sentence = re.compile(
        r"[^。！？.!?\n]*(?:知识库|文档|资料|knowledge\s*base|documentation)[^。！？.!?\n]*(?:没有|未涉及|不包含|无(?:法)?确定|no\s+(?:relevant\s+)?(?:definition|evidence|information)|not\s+(?:covered|available|contained)|does\s+not\s+(?:contain|provide))[^。！？.!?\n]*[。！？.!?]?",
        re.I,
    )
    softened = sentence.sub("当前最终证据未充分覆盖该方向，无法据此作出完整结论。", answer or "")
    marker = "当前最终证据未充分覆盖该方向，无法据此作出完整结论。"
    return marker.join(dict.fromkeys(part for part in softened.split(marker))) if softened.count(marker) > 1 else softened


def _unsupported_generation_claims(answer: str, evidence: str, query: str) -> list[str]:
    """Find technical additions absent from supplied Evidence.

    Identifiers/acronyms and concrete numeric parameters are checked; normal
    paraphrases are intentionally left to the semantic validator.
    """
    evidence_norm = evidence.casefold()
    query_norm = (query or "").casefold()
    unsupported: list[str] = []
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])|\n+", answer or "") if part.strip()]
    for sentence in sentences:
        tokens = _TECHNICAL_TOKEN_RE.findall(sentence)
        if any(
            token not in _NON_CLAIM_TOKENS
            and token.casefold() not in evidence_norm
            and token.casefold() not in query_norm
            for token in tokens
        ):
            unsupported.append(sentence)
            continue
        if _UNSUPPORTED_MECHANISM_RE.search(sentence) and not _UNSUPPORTED_MECHANISM_RE.search(evidence):
            unsupported.append(sentence)
            continue
        numeric_details = _NUMERIC_DETAIL_RE.findall(sentence)
        if any(value.casefold() not in evidence_norm and value.casefold() not in query_norm for value in numeric_details):
            unsupported.append(sentence)
    return list(dict.fromkeys(unsupported))


def _numeric_unit_conflicts(answer: str, evidence: str, query: str) -> list[str]:
    """Return claims whose numeric/unit pair is not present as a pair."""
    evidence_norm = (evidence or "").casefold()
    query_norm = (query or "").casefold()
    conflicts: list[str] = []
    for sentence in _answer_sentences(answer):
        details = _NUMERIC_DETAIL_RE.findall(sentence)
        if details and any(value.casefold() not in evidence_norm and value.casefold() not in query_norm for value in details):
            conflicts.append(sentence)
    return list(dict.fromkeys(conflicts))


def remove_unsupported_claims(answer: str, claims: tuple[str, ...] | list[str]) -> str:
    """Remove only validator-identified unsupported sentences after retry."""
    claim_set = {str(value).strip() for value in claims if str(value).strip()}
    if not claim_set:
        return answer or ""
    parts = [part.strip() for part in re.split(r"(?<=[。！？.!?])|\n+", answer or "") if part.strip()]
    return "\n".join(part for part in parts if part not in claim_set).strip()


def _answer_sentences(answer: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？.!?])|\n+", answer or "")
        if part.strip()
    ]


def salvage_supported_claims(
    answer: str,
    validation: ValidationResult | dict | None = None,
) -> str:
    """Keep independently supported claims while removing failed claims.

    Validation is deliberately claim-local here.  A failed claim must not
    erase neighboring facts that passed the same Evidence check.  The helper
    accepts the serialized validation dictionary used by the API as well as
    ``ValidationResult`` so it can be used at the final assembly boundary.
    """
    if isinstance(validation, ValidationResult):
        unsupported = set(validation.unsupported_claims)
        overclaims = set(validation.overclaim_claims)
        raw_negative = set(validation.raw_llm_negative_claims)
        negative_conflict = bool(validation.negative_claim_conflicts_with_coverage)
        lifecycle_conflict = bool(validation.lifecycle_state_conflicts)
        return_code_conflict = bool(validation.return_code_conflicts)
        parameter_conflicts = set(validation.parameter_name_conflicts)
    else:
        data = validation or {}
        unsupported = {str(value).strip() for value in data.get("unsupported_claims", ())}
        overclaims = {str(value).strip() for value in data.get("overclaim_claims", ())}
        raw_negative = {str(value).strip() for value in data.get("raw_llm_negative_claims", ())}
        negative_conflict = bool(data.get("negative_claim_conflicts_with_coverage"))
        lifecycle_conflict = bool(data.get("lifecycle_state_conflicts"))
        return_code_conflict = bool(data.get("return_code_conflicts"))
        parameter_conflicts = {str(value).strip() for value in data.get("parameter_name_conflicts", ())}

    kept: list[str] = []
    for sentence in _answer_sentences(answer):
        if sentence in unsupported or sentence in overclaims:
            continue
        if parameter_conflicts and any(value in sentence for value in parameter_conflicts):
            continue
        if lifecycle_conflict and _LIFECYCLE_CREATED_RE.search(sentence):
            continue
        if return_code_conflict and _WEAK_FAILURE_RE.search(sentence):
            continue
        # Remove only a negative claim that actually contradicts covered
        # Evidence.  A bounded diagnostic statement such as "仅凭 CPU 端序
        # 不能直接定因" is useful and must survive.
        if negative_conflict and sentence in raw_negative and not re.search(
            r"仅凭|不能(?:单独|直接)|需结合|仍需|不宜直接|not enough to establish|cannot alone",
            sentence,
            re.I,
        ):
            continue
        kept.append(sentence)
    return "\n".join(dict.fromkeys(kept)).strip()


def merge_salvaged_answers(
    first_answer: str,
    first_validation: ValidationResult | dict | None,
    retry_answer: str,
    retry_validation: ValidationResult | dict | None,
) -> str:
    """Compatibility helper for a retry that is a complete answer rewrite.

    Validation retry prompts request a full replacement.  Keeping the old
    first-generation buffer here would silently reintroduce duplicate openings,
    stale claims, and half of two different answers.  The first answer is used
    only when the provider returned no retry text at all.
    """
    del first_validation, retry_validation
    return (retry_answer or first_answer or "").strip()


def build_evidence_grounded_fallback(
    question: str,
    evidence: list[dict],
    required_facets: list[dict] | None = None,
    reasoning_trace: dict | None = None,
) -> str:
    """Build a small factual answer directly from selected Evidence.

    This is a generation failure path, not a second model.  It quotes the
    most relevant sentence from each selected evidence item and adds only a
    generic boundary note for an observation-dependent part of the question.
    """
    if required_facets is None:
        inferred_terms = re.findall(
            r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}",
            str(question or ""),
        )
        required_facets = [{"id": term, "terms": (term,)} for term in dict.fromkeys(inferred_terms)]
    else:
        required_facets = required_facets or []
    trace = reasoning_trace or {}
    def complete_sentences(content: str) -> list[str]:
        return [
            part.strip() for part in re.split(r"(?<=[。！？.!?；;])|\n+", content)
            if part.strip()
        ] or [content]

    lines = ["根据当前检索到的 Evidence，可确认："]
    selected: list[tuple[int, str]] = []
    supported_ids = set(trace.get("directly_covered_facets", [])) | set(trace.get("compositionally_covered_facets", []))
    for facet in required_facets:
        facet_id = str(facet.get("id") or "")
        if not facet_id:
            continue
        matches: list[tuple[int, str, int]] = []
        for index, item in enumerate(evidence, 1):
            content = re.sub(r"\s+", " ", str(item.get("content") or item.get("quote") or "")).strip()
            if not content or not _supports(item, facet):
                continue
            sentences = complete_sentences(content)
            best = max(
                sentences,
                key=lambda sentence: (
                    sum(_answer_term_matches(sentence, term) for term in _facet_terms(facet)),
                    -len(sentence),
                ),
            )
            matches.append((index, best, len(best)))
        if matches:
            index, sentence, _ = max(matches, key=lambda value: (-value[2], -value[0]))
            lines.append(f"- {facet_id}：{sentence}（证据{index}）")
            selected.append((index, sentence))
        elif facet_id not in supported_ids:
            lines.append(f"- {facet_id}：当前 Evidence 未直接覆盖该方向，资料不足以作出确定结论。")

    if not selected and not required_facets:
        candidates: list[tuple[int, int, str]] = []
        for index, item in enumerate(evidence, 1):
            content = re.sub(r"\s+", " ", str(item.get("content") or item.get("quote") or "")).strip()
            if content:
                candidates.append((0, index, complete_sentences(content)[0]))
        for _, index, sentence in candidates[:4]:
            lines.append(f"- {sentence}（证据{index}）")
            selected.append((index, sentence))
    if not selected:
        return ""
    question_text = str(question or "")
    diagnostic_requested = bool(re.search(
        r"根因|原因|是否可以.*(确定|断定)|能否.*(确定|断定)|cause|determin|root cause",
        question_text,
        re.I,
    ))
    uncovered = bool(
        trace.get("unsupported_facets")
        or trace.get("uncovered_relation_facets")
        or trace.get("uncovered_facets")
    )
    if diagnostic_requested or uncovered:
        lines.append("对于未被 Evidence 直接覆盖的判断方向，当前资料不足以作出确定结论，仍需结合具体现场信息进一步验证。")
    return "\n".join(lines)


def validate_answer(
    answer: str,
    rerank_top5: list[dict],
    query: str = "",
    *,
    candidate_pool: list[dict] | None = None,
    required_facets: list[dict] | None = None,
    relation_facets: list[dict] | None = None,
    facet_diagnostics: dict | None = None,
) -> ValidationResult:
    text = answer or ""
    evidence = "\n".join(str(item.get("content") or item.get("quote") or "") for item in rerank_top5)
    output_integrity_issues = _output_integrity_issues(text)
    parameter_name_conflicts = _parameter_name_conflicts(text, evidence, query)
    unsupported_claims = _unsupported_generation_claims(text, evidence, query)
    numeric_unit_conflicts = _numeric_unit_conflicts(text, evidence, query)
    claim_strengths, overclaim_claims = _claim_strengths(text, evidence)
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
    if unsupported_claims:
        reasons.append("回答引入了证据未支持的技术实体或具体参数")
    if output_integrity_issues:
        reasons.append("回答存在残缺或重复输出: " + ", ".join(output_integrity_issues))
    if parameter_name_conflicts:
        reasons.append("回答使用了 Evidence/问题之外的参数全名: " + ", ".join(parameter_name_conflicts))

    required_facets = required_facets or []
    candidate_pool = candidate_pool or rerank_top5
    relation_facets = relation_facets or []
    support = analyze_evidence_support(query, rerank_top5, required_facets, relation_facets)
    exact_api_conflicts = _exact_api_conflicts(text, rerank_top5, required_facets)
    concept_conflicts = semantic_concept_conflicts(query, rerank_top5, required_facets)
    action_conflicts = action_applicability_conflicts(query, text, rerank_top5)
    lifecycle_conflicts = _lifecycle_state_conflicts(text, evidence)
    return_code_conflicts = _explicit_return_code_conflicts(text, evidence)
    causal_conflicts = _causal_overclaim_conflicts(text, evidence)
    mechanism_conflicts = _mechanism_conflicts(text, evidence)
    overclaim_claims = list(dict.fromkeys((*overclaim_claims, *causal_conflicts)))
    if overclaim_claims:
        reasons.append("回答使用了证据强度不足的绝对化表述")
    if exact_api_conflicts:
        reasons.append("具体 API 语义来自相关接口而非当前 API Evidence: " + ", ".join(exact_api_conflicts))
    if concept_conflicts:
        reasons.append("Evidence 覆盖了相近但不同的语义概念: " + ", ".join(concept_conflicts))
    if action_conflicts:
        reasons.append("明确建议缺少 Evidence 或适用条件: " + ", ".join(action_conflicts))
    if lifecycle_conflicts:
        reasons.append("Evidence 仅支持 enabled 状态限制，回答将其扩大为 created 状态: " + ", ".join(lifecycle_conflicts))
    if return_code_conflicts:
        reasons.append("Evidence 已明确返回码，回答却将失败行为弱化: " + ", ".join(return_code_conflicts))
    if numeric_unit_conflicts and "回答引入了证据未支持的技术实体或具体参数" not in reasons:
        reasons.append("数字/单位组合未被 Evidence 完整支持")
    if causal_conflicts:
        reasons.append("回答把可诊断关联升级为未经支持的直接因果")
    if mechanism_conflicts:
        reasons.append("回答混淆了 QoS、Discovery、类型/序列化或网络机制: " + "; ".join(mechanism_conflicts))
    compositionally_covered = set(support["compositionally_covered_facets"])
    answer_covered_facets, answer_missing_facets, answer_facet_snippets = _answer_facet_coverage(
        text,
        query,
        required_facets,
        set(support.get("directly_covered_facets", [])) | compositionally_covered,
    )
    missing: list[str] = []
    negative: list[str] = []
    compositional_refusal: list[str] = []
    pool_relation_support = relation_candidate_map(candidate_pool, relation_facets)
    final_relation_support = relation_candidate_map(rerank_top5, relation_facets)
    missing_relations = [key for key, ids in pool_relation_support.items() if ids and not final_relation_support.get(key)]
    pool_constraint_support = relation_constraint_candidate_map(candidate_pool, relation_facets)
    final_constraint_support = relation_constraint_candidate_map(rerank_top5, relation_facets)
    raw_llm_negative_claims = _extract_raw_negative_claims(text)
    negative_claim_conflicts: list[str] = []
    covered_relation_ids = [str(value) for value in support.get("covered_relation_facets", [])]
    for claim in raw_llm_negative_claims:
        claim_lower = claim.lower()
        matched_relation_ids: list[str] = []
        for relation_id in covered_relation_ids:
            if not relation_id.isdigit() or int(relation_id) >= len(relation_facets):
                continue
            relation = relation_facets[int(relation_id)]
            terms = [
                str(relation.get("subject") or "").lower(),
                str(relation.get("object") or "").lower(),
                str(relation.get("relation") or "").lower(),
            ]
            technical_terms = [
                term for term in re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}", " ".join(terms))
                if len(term) >= 3 or any("\u4e00" <= char <= "\u9fff" for char in term)
            ]
            if technical_terms and any(term.lower() in claim_lower for term in technical_terms):
                matched_relation_ids.append(relation_id)
        # If the negative claim is about a concrete rule, prefer the matching
        # covered constraint relation over its role/presence prerequisites.
        # This keeps diagnostics targeted (for example, the compatibility
        # relation rather than both offered/requested presence relations).
        matching_constraint_ids = [
            relation_id for relation_id in matched_relation_ids
            if relation_requires_constraint(relation_facets[int(relation_id)])
        ]
        negative_claim_conflicts.extend(
            "relation:" + relation_id
            for relation_id in (matching_constraint_ids or matched_relation_ids)
        )
        for facet in required_facets:
            facet_id = str(facet.get("id") or "")
            if facet_id in support.get("directly_covered_facets", []) or facet_id in compositionally_covered:
                # A bounded sentence may acknowledge a covered fact and then
                # state that a narrower OS/runtime detail is absent.  That is
                # not a contradiction of the covered DDS facet.
                if re.search(
                    r"虽然.{0,160}(?:说明|支持|覆盖|有).{0,100}(?:但|but).{0,100}(?:未提供|未涉及|未说明|不足|未覆盖)",
                    claim,
                    re.I | re.S,
                ):
                    continue
                terms = _facet_terms(facet)
                # A facet can be present while its requested constraint is
                # absent.  Do not turn a conservative constraint-level claim
                # into a contradiction merely because the object name is
                # covered; relation constraint coverage is the authoritative
                # check for that narrower target.
                uncovered_constraint_for_facet = any(
                    relation_requires_constraint(relation)
                    and str(index) not in set(support.get("relation_constraint_covered", []))
                    and any(
                        object_term.lower() in str(relation.get("object") or "").lower()
                        or str(relation.get("object") or "").lower() in object_term.lower()
                        for object_term in _facet_terms(facet)
                    )
                    for index, relation in enumerate(relation_facets)
                )
                if (
                    any(term.lower() in claim_lower for term in terms if term)
                    and not (
                        _CONSTRAINT_NEGATIVE_TARGET_RE.search(claim_lower)
                        and uncovered_constraint_for_facet
                    )
                ):
                    negative_claim_conflicts.append("facet:" + facet_id)
        if not matched_relation_ids:
            covered_constraint_ids = [
                relation_id for relation_id, ids in final_constraint_support.items()
                if ids and relation_id in covered_relation_ids
            ]
            if covered_constraint_ids:
                negative_claim_conflicts.extend("relation:" + relation_id for relation_id in covered_constraint_ids)
    negative_claim_conflicts = list(dict.fromkeys(negative_claim_conflicts))
    missing_relation_constraints = [
        str(index) for index, relation in enumerate(relation_facets)
        if relation_requires_constraint(relation)
        and (pool_relation_support.get(str(index)) or pool_constraint_support.get(str(index)))
        and not final_constraint_support.get(str(index))
    ]
    ignored_missing: list[str] = [
        str(item.get("facet"))
        for item in (facet_diagnostics or {}).get("rejected_noise_facets", [])
        if isinstance(item, dict) and item.get("facet")
    ]

    def _relation_covers_facet(facet_id: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", facet_id.lower())
        for index, relation in enumerate(relation_facets):
            if not final_relation_support.get(str(index)):
                continue
            subject = str(relation.get("subject") or "").lower()
            subject_normalized = re.sub(r"[^a-z0-9]", "", subject)
            if subject_normalized and (
                normalized == subject_normalized
                or normalized.endswith(subject_normalized)
                or subject_normalized.endswith(normalized)
            ):
                return True
        return False
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
            if _relation_covers_facet(facet_id):
                ignored_missing.append(facet_id)
            else:
                missing.append(facet_id)
    if answer_missing_facets:
        reasons.append(
            "回答未分别覆盖已有 Evidence 支持的 required facets: "
            + ", ".join(answer_missing_facets)
        )
        missing.extend(answer_missing_facets)
    if missing:
        reasons.append("最终证据/回答未覆盖已召回的 required facets: " + ", ".join(dict.fromkeys(missing)))
    if negative:
        reasons.append("回答对已有候选证据的 facet 作出了绝对不存在声明: " + ", ".join(dict.fromkeys(negative)))
    if missing_relations:
        reasons.append("最终证据未覆盖已召回的 required relations: " + ", ".join(missing_relations))
        missing.extend("relation:" + key for key in missing_relations)
    if missing_relation_constraints:
        reasons.append("最终证据未覆盖已召回关系的具体约束: " + ", ".join(missing_relation_constraints))
        missing.extend("relation:" + key for key in missing_relation_constraints)
    if negative_claim_conflicts:
        reasons.append("LLM 负向结论与已覆盖证据冲突: " + ", ".join(negative_claim_conflicts))
        negative.extend(negative_claim_conflicts)
    relation_chain = bool(support.get("relation_chain_supported"))
    if relation_chain and _COMPOSITIONAL_REFUSAL_RE.search(text):
        negative.extend("relation:" + key for key in support.get("covered_relation_facets", []))
        reasons.append("回答忽略了已覆盖的关系证据链并以缺少场景原句拒答")
    if compositionally_covered and _COMPOSITIONAL_REFUSAL_RE.search(text):
        compositional_refusal = sorted(compositionally_covered)
        reasons.append("回答忽略了可组合证据链并以缺少场景原句拒答: " + ", ".join(compositional_refusal))
    missing_relation_values = tuple(dict.fromkeys("relation:" + key for key in missing_relations))
    missing_relation_constraint_values = tuple(dict.fromkeys("relation:" + key for key in missing_relation_constraints))
    contradicted = tuple(dict.fromkeys(negative))
    return ValidationResult(
        status="answered" if not reasons else "insufficient_evidence",
        reasons=tuple(reasons),
        missing_required_facets=tuple(dict.fromkeys(missing)),
        negative_claim_facets=contradicted,
        compositional_refusal_facets=tuple(compositional_refusal),
        missing_relations=tuple(dict.fromkeys((*missing_relation_values, *missing_relation_constraint_values))),
        missing_relation_constraints=missing_relation_constraint_values,
        missing_side_states=tuple(facet for facet in missing if not str(facet).startswith("relation:")),
        contradicted_negative_claims=tuple(dict.fromkeys(negative)),
        ignored_missing_facets=tuple(dict.fromkeys(ignored_missing)),
        raw_llm_negative_claims=tuple(raw_llm_negative_claims),
        negative_claim_conflicts_with_coverage=tuple(negative_claim_conflicts),
        generation_evidence_conflict=bool(negative_claim_conflicts),
        unsupported_claims=tuple(unsupported_claims),
        evidence_strength={"claims": claim_strengths, "overclaim_claims": list(overclaim_claims), "overall": "unsupported" if unsupported_claims or overclaim_claims else "direct_fact"},
        overclaim_detected=bool(overclaim_claims),
        overclaim_claims=tuple(overclaim_claims),
        exact_api_conflicts=tuple(exact_api_conflicts),
        semantic_concept_conflicts=tuple(concept_conflicts),
        action_applicability_conflicts=tuple(action_conflicts),
        supported_claims=tuple(_answer_sentences(salvage_supported_claims(text, {
            "unsupported_claims": unsupported_claims,
            "overclaim_claims": overclaim_claims,
            "raw_llm_negative_claims": raw_llm_negative_claims,
            "negative_claim_conflicts_with_coverage": negative_claim_conflicts,
            "lifecycle_state_conflicts": lifecycle_conflicts,
            "return_code_conflicts": return_code_conflicts,
            "mechanism_conflicts": mechanism_conflicts,
        }))),
        causal_overclaim_claims=tuple(causal_conflicts),
        lifecycle_state_conflicts=tuple(lifecycle_conflicts),
        numeric_unit_conflicts=tuple(numeric_unit_conflicts),
        return_code_conflicts=tuple(return_code_conflicts),
        mechanism_conflicts=tuple(mechanism_conflicts),
        answer_covered_facets=tuple(answer_covered_facets),
        answer_missing_facets=tuple(answer_missing_facets),
        answer_facet_snippets=answer_facet_snippets,
        output_integrity_issues=tuple(output_integrity_issues),
        parameter_name_conflicts=tuple(parameter_name_conflicts),
    )
