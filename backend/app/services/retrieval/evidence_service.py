"""Facet-aware final-evidence selection."""

from __future__ import annotations

import re
from uuid import uuid4
from typing import Any, Iterable

from app.services.query_rewrite_service import QueryRewrite, rewrite_query

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}")
# Auxiliary retrieval hints only; required coverage comes from user wording.
_FACET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("instance_registration", ("实例注册", "注册实例", "register_instance", "register")), ("write", ("datawriter_write", "write", "写入", "写数据")),
    ("dispose", ("dispose", "销毁实例", "释放实例")), ("read", ("read", "读取")), ("take", ("take", "取出")),
    ("listener", ("listener", "监听器", "回调")), ("waitset", ("waitset", "wait set", "同步等待")),
    ("condition", ("readcondition", "statuscondition", "querycondition", "condition")), ("qos", ("qos", "服务质量")),
    ("reliability", ("reliability", "可靠性", "可靠", "best_effort", "best-effort", "reliable")), ("history", ("history", "历史")),
    ("resource_limits", ("resourcelimits", "resource_limits", "资源限制", "资源上限")), ("durability", ("durability", "持久性")),
    ("partition", ("partition", "分区")), ("topic", ("topic", "主题")), ("type", ("数据类型", "类型一致", "类型不一致", "type")),
    ("domain", ("domainparticipant", "domain id", "domain")), ("idl", ("idl", "结构体")),
    ("serialization", ("序列化", "serialize")), ("deserialization", ("反序列化", "deserialize")),
    ("xml_qos", ("xml", "xml qos", "配置文件")), ("network", ("网络", "端口", "传输", "发现")),
    ("metatraffic", ("metatraffic", "meta traffic")), ("usertraffic", ("usertraffic", "user traffic")),
    ("discovery", ("discovery", "发现地址", "发现阶段", "发现协议")),
    ("logging", ("日志", "计数器", "状态")), ("blocking", ("阻塞", "卡住", "锁竞争", "死锁")),
    ("api_lifecycle", ("api", "创建", "生命周期", "调用顺序")),
    ("deadline", ("deadline", "deadlineqospolicy", "截止期限", "period", "deadline missed")),
    ("liveliness", ("liveliness", "livelinessqospolicy", "存活性", "活性", "lease_duration", "liveliness_changed")),
    ("fragmentation", ("fragmentation", "datafrag", "data frag", "nackfrag", "nack frag", "分片")),
    ("reliable_retransmission", ("retransmission", "reliable", "heartbeat", "acknack", "nackfrag", "重传")),
    ("mtu", ("mtu", "maximum transmission unit", "最大传输单元")),
    ("endianness", ("endianness", "endian", "端序", "大小端")),
    ("rtps_message_little_endian", ("rtps_message_little_endian", "little endian", "message endian")),
    ("read_next_sample", ("read_next_sample", "read next sample")),
    ("take_next_sample", ("take_next_sample", "take next sample")),
    ("return_loan", ("return_loan", "return loan", "loaned sequence", "loaned buffer")),
    ("qos_mutability", ("qos mutability", "immutable qos", "immutable policy", "cannot be changed after an entity is enabled", "不可变qos", "不可变 qos", "使能后不可修改", "enabled 后不可修改")),
)
_SCENARIO_ALIASES = ("收不到数据", "无样本", "看不到", "看不到消息", "没有数据", "丢消息", "数据丢失", "通信失败", "故障", "异常")
_QUERY_STOP_WORDS = {
    "a", "an", "and", "are", "be", "can", "could", "do", "does", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "what", "when", "which", "with", "why",
    "请", "从", "中", "的", "了", "和", "与", "及", "或", "如何", "什么", "哪些", "有", "是", "为",
    "说明", "解释", "区别", "分别", "时候", "需要", "可以", "应该", "问题", "操作", "步骤", "资料", "原始", "给出",
    "通信", "协议", "详细", "实现", "说明", "支持", "内部", "所有", "算法", "线程", "源代码", "实验", "步骤",
}
_ENGINEERING_CHANGE_RE = re.compile(r"(?:部分|只|未(?:替换|同步|更新)|变更|修改|增加|删除|替换|不一致|风险|问题|处理|影响|partial|only|not\s+(?:replace|update|sync)|change|replace|inconsisten|risk|impact)", re.I)

# Semantic identity is deliberately stricter than lexical overlap.  The
# identity is attached to a required facet and is also detected in evidence;
# a shared word such as lifecycle, sysctl, topic, or API never bridges two
# different concepts by itself.
_CONCEPT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("entity_lifecycle", (
        "entity lifecycle", "create_topic", "create_datawriter", "create_datareader",
        "create_publisher", "create_subscriber", "create_participant", "delete_topic",
        "delete_datawriter", "delete_datareader", "delete_contained_entities",
        "parent entity", "child entity", "reinitialization", "re-initialization",
        "reinitialize", "重新初始化", "实体创建", "实体删除", "父子实体",
    )),
    ("reader_data_lifecycle", (
        "readerdatalifecycle", "reader data lifecycle", "reader_data_lifecycle",
        "readerdata lifecycle", "reader data lifecycle qos", "readerdatalifecycleqospolicy",
    )),
    ("zrdds_sysctl", ("sysctl.global.", "zrdds sysctl", "zrdds_sysctl")),
    ("linux_sysctl", ("linux sysctl", "kernel sysctl", "/proc/sys", "sysctl -w", "ethtool", "irqbalance")),
    ("standard_dds_api", (
        "standard dds", "dds standard api", "create_topic", "create_datawriter",
        "create_datareader", "domainparticipant::create", "create_topic()",
    )),
    ("zrdds_extension_api", (
        "zrdds extension", "simplified interface", "simple interface", "ddsif",
        "create_datawriter_with_topic", "pubtopic", "unpubtopic", "扩展接口", "简化接口",
    )),
    ("exact_api:read_next_sample", ("read_next_sample", "read next sample")),
    ("exact_api:take_next_sample", ("take_next_sample", "take next sample")),
    ("exact_api:return_loan", ("return_loan", "return loan", "loaned sequence", "loaned buffer")),
    ("exact_api:read", ("read()", "read 方法", "read method")),
    ("exact_api:take", ("take()", "take 方法", "take method")),
    ("qos_mutability", ("immutable qos", "immutable policy", "cannot be changed after an entity is enabled", "不可变qos", "不可变 qos", "使能后不可修改", "enabled after")),
)

_BOUNDARY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FRESH", ("最新", "本周", "this week", "latest", "current cve", "cve", "security advisory", "current security", "安全公告", "下一版本", "next release", "发布日期", "roadmap")),
    ("EXPERIMENT", ("吞吐", "throughput", "p99", "延迟", "latency", "最高", "最大", "benchmark", "基准", "性能", "irq", "网卡", "cpu affinity", "ethtool", "最优", "optimal")),
    ("NEED-CONTEXT", ("唯一根因", "直接判断", "直接改", "directly determine", "directly modify", "根因", "why did", "root cause", "without pcap", "no pcap", "没有 pcap", "without code", "no code", "without a packet capture", "packet capture", "no runtime log", "segmentation fault", "偶发丢")),
)

_NETWORK_DIAGNOSTIC_RE = re.compile(
    r"(?:metatraffic|meta[_ ]traffic|usertraffic|user[_ ]traffic|发现地址|发现阶段|"
    r"网络|网卡|\bNIC\b|\bIP\b|地址).{0,100}?"
    r"(?:不可达|不通|通信失败|收不到|排查|定位|阶段|诊断|故障|unreachable|"
    r"not reachable|diagnos|troubleshoot|failure|stage)",
    re.I,
)
_PERFORMANCE_INTENT_RE = re.compile(
    r"吞吐|throughput|p99|延迟|latency|benchmark|基准|性能|最高|最优|optimal|"
    r"保证数值|guaranteed maximum|实验|压测",
    re.I,
)

# A query may contain both a knowledge request and a request for a final
# incident conclusion.  The latter needs现场输入, but it must not suppress
# the former when the requested fact has direct evidence.  These markers are
# intentionally generic: they describe the shape of a fact request rather
# than any one product, parameter, or regression case.
_FACT_REQUEST_RE = re.compile(
    r"有哪些|哪些|配置|参数|可核对|可检查|排查路径|如何(?:使用|配置|检查|判断|区分)|"
    r"what|which|list|configuration|config(?:ure)?|parameter|how\s+to|"
    r"meaning|difference|semantics|check|inspect",
    re.I,
)
_SPECIFIC_DIAGNOSTIC_RE = re.compile(
    r"唯一|具体(?:根因|原因|错误|子消息|字段|问题)|直接(?:判断|确定|定因)|"
    r"根因|原因是什么|exact\s+(?:root\s+cause|cause|submessage|field)|"
    r"root\s+cause|without\s+(?:pcap|a\s+packet\s+capture)|没有\s*pcap|"
    r"packet\s+capture|no\s+(?:pcap|code|runtime\s+log)|"
    r"(?:definitely|uniquely|directly)\s+(?:caused|cause|determine)|"
    r"confirm\s+which\s+.*(?:caused|cause)|只能指出|which\s+exact",
    re.I,
)

_ABSENCE_BOUNDARY_TERMS = ("量子", "quantum", "星际", "interstellar", "未来产品", "future product", "商业授权", "commercial license", "价格", "price", "折扣", "discount", "sla", "采购", "procurement", "互操作", "interoperability", "兼容矩阵", "compatibility matrix", "100%")
_ACTION_TERMS = {
    "Batch": ("batch", "批处理"),
    "BEST_EFFORT": ("best_effort", "best-effort", "尽力而为"),
    "CPU affinity": ("cpu affinity", "cpu 亲和", "绑核"),
    "read→take": ("read→take", "read 改成 take", "read to take", "改用 take"),
    "delete_contained_entities": ("delete_contained_entities", "删除所有包含实体", "删除包含实体"),
    "ResourceLimits": ("resourcelimits", "resource limits", "资源限制"),
    "purge": ("purge", "清理延迟", "purge delay"),
    "Jumbo Frame": ("jumbo frame", "巨型帧"),
    "QoS modification": ("set_qos", "set qos", "修改qos", "修改 qos", "调整qos", "调整 qos"),
}
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


def concept_identities(text: str) -> set[str]:
    """Return semantic concept identities present in text.

    This is a small vocabulary bridge for disambiguation, not an answer
    generator.  More specific identities are retained alongside their family
    so callers can require an exact API or an exact interface family.
    """
    lowered = str(text or "").lower()
    found: set[str] = set()
    for identity, aliases in _CONCEPT_ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            found.add(identity)
    # Generic create/delete wording is only an entity-lifecycle identity when
    # both sides of the lifecycle are present.  This prevents a lone
    # ``delete`` in an unrelated paragraph from covering the concept.
    if (
        re.search(r"create[_ ](?:topic|datawriter|datareader|publisher|subscriber|participant)|实体创建|创建.*(?:topic|writer|reader|实体)", lowered)
        and re.search(r"delete[_ ](?:topic|datawriter|datareader|contained|publisher|subscriber|participant)|实体删除|销毁.*(?:topic|writer|reader|实体)", lowered)
    ):
        found.add("entity_lifecycle")
    return found


def facet_concept_identity(facet: dict[str, Any] | str) -> str | None:
    """Resolve the exact semantic identity required by a facet."""
    if isinstance(facet, dict) and facet.get("concept_id"):
        return str(facet["concept_id"])
    value = str(facet.get("id") if isinstance(facet, dict) else facet or "")
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    # Generic QoS is a different concept from the enabled-state mutability
    # contract.  Keep the generic name untyped unless the query explicitly
    # asks for immutable/enabled-state semantics.
    if normalized in {"qos", "qospolicy", "qospolicies"}:
        return None
    for identity, aliases in _CONCEPT_ALIASES:
        if normalized == re.sub(r"[^a-z0-9]+", "", identity.lower()):
            return identity
        if any(normalized == re.sub(r"[^a-z0-9]+", "", alias.lower()) for alias in aliases):
            return identity
    lowered = value.lower()
    if "entity lifecycle" in lowered or "实体生命周期" in lowered:
        return "entity_lifecycle"
    if "readerdata" in normalized or "reader data lifecycle" in lowered:
        return "reader_data_lifecycle"
    return None


def _concept_supported(item: dict[str, Any], facet: dict[str, Any]) -> bool:
    required_identity = facet_concept_identity(facet)
    if not required_identity:
        return True
    return required_identity in concept_identities(_text(item))


def semantic_concept_conflicts(
    query: str,
    evidence: list[dict[str, Any]],
    required_facets: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Report related-but-not-identical concepts that could be overcovered."""
    conflicts: set[str] = set()
    evidence_concepts = set().union(*(concept_identities(_text(item)) for item in evidence)) if evidence else set()
    for facet in required_facets or []:
        required_identity = facet_concept_identity(facet)
        if not required_identity or required_identity in evidence_concepts:
            continue
        family = required_identity.split(":", 1)[0]
        related = sorted(identity for identity in evidence_concepts if identity.split(":", 1)[0] == family)
        if related:
            conflicts.add(f"{required_identity}:{','.join(related)}")
    lowered = str(query or "").lower()
    if "entity lifecycle" in lowered or "实体生命周期" in lowered:
        if "reader_data_lifecycle" in evidence_concepts and "entity_lifecycle" not in evidence_concepts:
            conflicts.add("entity_lifecycle:reader_data_lifecycle")
    if "linux sysctl" in lowered or "内核 sysctl" in lowered:
        if "zrdds_sysctl" in evidence_concepts and "linux_sysctl" not in evidence_concepts:
            conflicts.add("linux_sysctl:zrdds_sysctl")
    if ("standard" in lowered and "api" in lowered) and "zrdds_extension_api" in evidence_concepts and "standard_dds_api" not in evidence_concepts:
        conflicts.add("standard_dds_api:zrdds_extension_api")
    return sorted(conflicts)


def evidence_strength_summary(
    evidence: list[dict[str, Any]],
    required_facets: list[dict[str, Any]],
    relation_facets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expose direct/inference/unsupported strength at target level."""
    relation_facets = relation_facets or []
    facet_strength: dict[str, str] = {}
    for facet in required_facets:
        facet_id = str(facet.get("id") or "")
        supported = any(_concept_supported(item, facet) and facet_id in facets_for_candidate(item, [facet]) for item in evidence)
        facet_strength[facet_id] = "direct_fact" if supported else "unsupported"
    relation_data = relation_coverage(evidence, relation_facets)
    relation_strength = {
        str(index): "direct_fact" if str(index) in relation_data["covered_relation_facets"] else "unsupported"
        for index in range(len(relation_facets))
    }
    overall = "direct_fact" if facet_strength and all(value == "direct_fact" for value in facet_strength.values()) and all(value == "direct_fact" for value in relation_strength.values()) else (
        "supported_inference" if evidence and any(value == "direct_fact" for value in (*facet_strength.values(), *relation_strength.values())) else "unsupported"
    )
    return {"facets": facet_strength, "relations": relation_strength, "overall": overall}


def diagnostic_stage_plan(query: str) -> dict[str, Any]:
    """Build an earliest-confirmed-stage diagnostic plan from user facts."""
    text = str(query or "").lower()
    stages = (
        ("participant_discovery", ("participant discovery", "participant发现", "参与者发现", "发现不到 participant", "discovery failed")),
        ("endpoint_matching", ("endpoint discovery", "endpoint unmatched", "endpoint match", "端点发现", "端点未匹配", "writer/reader没有匹配", "没有匹配")),
        ("user_data_transport", ("no data", "没有 data", "没有用户数据", "user data", "data not arrive", "数据未到达")),
        ("reliability_retransmission", ("heartbeat", "acknack", "nackfrag", "重传", "retransmission", "可靠传输", "丢包")),
        ("reader_cache_application_read", ("read_next_sample", "read()", "take()", "reader cache", "reader缓存", "数据已到 reader", "到达 reader")),
        ("application_processing", ("on_data_available", "callback", "回调", "数据库写入", "阻塞", "backlog", "积压", "死锁")),
    )
    confirmed: list[str] = []
    first_failure: str | None = None
    if re.search(r"participant.{0,30}(?:discovered|found|已发现|发现)", text, re.I) and not re.search(r"(?:not|未|没|无法).{0,10}(?:discover|发现)", text, re.I):
        confirmed.append("participant_discovery")
    if re.search(r"(?:discovery failed|无法发现|发现失败|没有发现).{0,20}(?:participant|参与者)?", text, re.I):
        first_failure = "participant_discovery"
    elif re.search(r"(?:writer|reader|endpoint).{0,50}(?:unmatched|not match|没有匹配|未匹配|不匹配)", text, re.I):
        first_failure = "endpoint_matching"
    elif re.search(r"(?:data|sample).{0,40}(?:not arrive|没有|未到|丢)", text, re.I) and "reader" not in text:
        first_failure = "user_data_transport"
    elif re.search(r"(?:data|heartbeat).{0,50}(?:arrive|reached|到|收到).{0,50}(?:read_next_sample|read\(\)|无数据|没有数据)", text, re.I):
        confirmed.extend(("participant_discovery", "endpoint_matching", "user_data_transport"))
        first_failure = "reader_cache_application_read"
    elif re.search(r"(?:on_data_available|callback|回调|数据库|阻塞|backlog|积压|死锁)", text, re.I):
        confirmed.extend(("participant_discovery", "endpoint_matching", "user_data_transport"))
        first_failure = "application_processing"
    elif re.search(r"(?:heartbeat|acknack|nackfrag|重传|retransmission)", text, re.I):
        confirmed.extend(("participant_discovery", "endpoint_matching"))
        first_failure = "reliability_retransmission"
    elif first_failure is None and confirmed:
        first_failure = "endpoint_matching"
    confirmed = list(dict.fromkeys(confirmed))
    return {
        "ordered_stages": [stage for stage, _ in stages],
        "confirmed_stages": confirmed,
        "first_failure_stage": first_failure,
        "next_validation": {
            "participant_discovery": "确认 SPDP/参与者发现及地址配置",
            "endpoint_matching": "确认 SEDP、Topic、Type、QoS、Partition 和匹配状态",
            "user_data_transport": "确认 Writer 到 Reader 的 DATA/DATAFRAG 路径和抓包",
            "reliability_retransmission": "确认 Heartbeat、AckNack、NackFrag 与重传状态",
            "reader_cache_application_read": "确认 Reader 缓存、状态及是否被其他线程 read/take",
            "application_processing": "确认回调耗时、线程积压、队列和应用处理路径",
        }.get(first_failure or "", "先获取能区分上述阶段的最小日志或抓包"),
    }


def classify_boundary(
    query: str,
    evidence: list[dict[str, Any]],
    required_facets: list[dict[str, Any]] | None = None,
    *,
    requested_version: str | None = None,
    version_status_value: str | None = None,
) -> str | None:
    """Classify policy boundaries before generation can add unsupported detail."""
    text = str(query or "").lower()
    if requested_version and version_status_value in {"UNKNOWN", "MISMATCH", "MIXED", "VERSION-GAP"}:
        return "VERSION-GAP"
    # Network troubleshooting is a fact/diagnostic route even when the
    # question mentions a NIC or IP.  Those words alone must not activate the
    # performance-experiment fallback; only an explicit performance intent
    # does.  This keeps the rule general for metatraffic/usertraffic, address,
    # and interface diagnostics.
    if _NETWORK_DIAGNOSTIC_RE.search(text) and not _PERFORMANCE_INTENT_RE.search(text):
        return None
    for boundary, patterns in _BOUNDARY_PATTERNS:
        # NEED-CONTEXT is a facet-local boundary.  A mixed question such as
        # "which settings should I check, and can they prove the root cause"
        # still has an answerable fact unit when the selected evidence covers
        # that unit.  Keep the boundary only for diagnostic-only requests or
        # when no requested fact has usable evidence.
        if boundary == "NEED-CONTEXT" and any(pattern.lower() in text for pattern in patterns):
            covered = set().union(*(facets_for_candidate(item, required_facets or []) for item in evidence)) if evidence else set()
            has_fact_unit = bool(_FACT_REQUEST_RE.search(text)) and bool(covered)
            missing_observation = bool(re.search(r"没有\s*pcap|no\s+(?:pcap|code|runtime\s+log)|without\s+(?:pcap|a\s+packet\s+capture|code)|没有\s*代码|无\s*运行日志", text, re.I))
            diagnostic_only = bool(_SPECIFIC_DIAGNOSTIC_RE.search(text)) and (not has_fact_unit or missing_observation)
            if has_fact_unit and not diagnostic_only:
                return None
        if any(pattern.lower() in text for pattern in patterns):
            return boundary
    if any(term in text for term in _ABSENCE_BOUNDARY_TERMS):
        return "OUT-KB"
    target_covered = any(
        facets_for_candidate(item, required_facets or [])
        for item in evidence
    )
    # A multi-facet engineering question can have valid partial evidence even
    # when the prose anchor is not repeated verbatim in an English chunk.  Do
    # not turn that partial coverage into an OUT-KB refusal.
    if evidence and not target_covered and not has_specific_query_support(query, evidence, required_facets):
        return "OUT-KB"
    return None


def answerability_summary(
    query: str,
    evidence: list[dict[str, Any]],
    required_facets: list[dict[str, Any]],
    optional_facets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return facet-local coverage and boundary state for audit and routing.

    ``NEED-CONTEXT`` is attached to the diagnostic unit when a question asks
    for a specific incident conclusion.  It is not allowed to erase covered
    fact facets.  The summary is observational; the existing evidence
    thresholds and semantic identity checks remain authoritative.
    """
    optional_facets = optional_facets or []
    required = list(required_facets or [])
    evidence_by_facet = facet_candidate_map(evidence, required)
    covered = [str(facet["id"]) for facet in required if evidence_by_facet.get(str(facet["id"]))]
    uncovered = [str(facet["id"]) for facet in required if not evidence_by_facet.get(str(facet["id"]))]
    fact_unit = bool(_FACT_REQUEST_RE.search(str(query or "")))
    diagnostic_unit = bool(_SPECIFIC_DIAGNOSTIC_RE.search(str(query or "")))
    boundary_by_facet: dict[str, str | None] = {facet_id: None for facet_id in covered}
    if diagnostic_unit:
        boundary_by_facet["diagnostic_conclusion"] = "NEED-CONTEXT"
    if not fact_unit and diagnostic_unit:
        boundary_by_facet = {facet_id: "NEED-CONTEXT" for facet_id in (covered or uncovered)}
    answerable = list(covered) if fact_unit else ([] if diagnostic_unit else list(covered))
    unanswerable = list(uncovered)
    if diagnostic_unit:
        unanswerable.append("diagnostic_conclusion")
    unanswerable = list(dict.fromkeys(unanswerable))
    if answerable and unanswerable:
        status = "PARTIAL_ANSWER"
    elif answerable:
        status = "ANSWER"
    else:
        status = "NO_ANSWER"
    return {
        "detected_facets": [str(facet["id"]) for facet in required] + [str(facet["id"]) for facet in optional_facets],
        "core_facets": [str(facet["id"]) for facet in required],
        "optional_facets": [str(facet["id"]) for facet in optional_facets],
        "evidence_by_facet": evidence_by_facet,
        "covered_facets": covered,
        "partially_covered_facets": [],
        "uncovered_facets": uncovered,
        "boundary_by_facet": boundary_by_facet,
        "overall_boundary": "NEED-CONTEXT" if diagnostic_unit else None,
        "answerable_facets": answerable,
        "unanswerable_facets": unanswerable,
        "answerability_status": status,
    }


def boundary_answer(boundary_type: str, requested_version: str | None = None) -> dict[str, Any]:
    """Return a non-generative answer for a classified boundary."""
    messages = {
        "OUT-KB": "当前知识库没有覆盖该问题所需的具体资料，无法编造数字、参数、兼容矩阵、价格或未来能力。",
        "EXPERIMENT": "当前资料不足以给出可保证的性能、硬件或系统数值；可以设计基准测试，并需结合实测结果验证候选配置。",
        "NEED-CONTEXT": "仅凭当前问题描述不足以确认具体根因或代码修改。请补充能区分阶段的最小输入，例如相关日志、pcap、代码/栈信息和实际 QoS 配置。",
        "FRESH": "静态知识库不能确认最新安全信息或未来产品计划；需要核对当前依赖版本、实际部署组件和最新官方公告。",
        "VERSION-GAP": f"当前资料不能确认指定版本 {requested_version or ''} 的适用性；未将其他版本或未知版本资料当作该版本事实。",
    }
    return {"answer": messages.get(boundary_type, "当前证据不足以支持该结论。"), "status": "insufficient_evidence", "answer_status": boundary_type, "boundary_type": boundary_type}


def action_applicability_conflicts(query: str, answer: str, evidence: list[dict[str, Any]]) -> list[str]:
    """Find explicit remediation advice lacking evidence or scenario context."""
    query_text = str(query or "").lower()
    evidence_text = " ".join(_text(item) for item in evidence).lower()
    answer_text = str(answer or "").lower()
    conflicts: list[str] = []
    action_markers = re.compile(
        r"增大|提高|调大|调整|修改|切换|启用|设置|改用|扩展|增加|减少|"
        r"increase|raise|adjust|modify|switch|enable|set|change|tune|use",
        re.I,
    )
    qualifying_markers = re.compile(
        r"如果|若|当|确认|证实|达到上限|已满|已观测|观察到|满足条件|"
        r"if|when|once|confirm|confirmed|observed|reached|condition|candidate|候选",
        re.I,
    )
    proven_condition = bool(re.search(
        r"已确认|确认.*(?:上限|满|不足|丢失|积压|不兼容)|观察到|证实|"
        r"confirmed|observed|proven|reached\s+(?:the\s+)?limit|at\s+capacity",
        query_text,
        re.I,
    ))
    for action, aliases in _ACTION_TERMS.items():
        if not any(alias.lower() in answer_text for alias in aliases):
            continue
        # Mentioning a setting as a diagnostic object is not a remediation.
        # Only an imperative/explicit change requires applicability proof.
        alias_positions = [answer_text.find(alias.lower()) for alias in aliases if answer_text.find(alias.lower()) >= 0]
        action_window = " ".join(
            answer_text[max(0, position - 80):position + 100]
            for position in alias_positions
        )
        explicit_action = bool(action_markers.search(action_window))
        if not explicit_action:
            continue
        evidence_support = any(alias.lower() in evidence_text for alias in aliases)
        answer_is_qualified = bool(qualifying_markers.search(action_window))
        condition_support = proven_condition and answer_is_qualified
        if not evidence_support or not condition_support:
            conflicts.append(action)
    return conflicts


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


def has_specific_query_support(
    query: str,
    evidence: list[dict[str, Any]],
    required_facets: list[dict[str, Any]] | None = None,
) -> bool:
    """Check whether evidence shares a non-instructional query anchor.

    Product names and generic question words are intentionally removed.  The
    check is a conservative signal for a generation refusal; it never proves
    that an answer is correct and does not select or inject evidence.
    """
    # Exact required-facet coverage is already a stronger query-specific
    # anchor than a prose n-gram.  This matters for mixed-language questions
    # where the English API is present in Evidence but surrounding Chinese
    # scenario words are not repeated verbatim.
    if required_facets and any(
        facets_for_candidate(item, required_facets)
        for item in evidence
    ):
        return True
    facet_text = " ".join(
        str(term)
        for facet in (required_facets or [])
        for term in facet.get("terms", ())
    ).lower()
    facet_ascii = set(re.findall(r"[a-z][a-z0-9_.+\-]*", facet_text))
    def _cjk_ngrams(value: str) -> set[str]:
        # Do not let a generic phrase such as ``通信协议`` bridge together
        # with a specific phrase through adjacent Chinese bigrams/trigrams.
        # Remove known instructional terms before making conservative
        # three-character anchors.
        for stop in sorted(_QUERY_STOP_WORDS, key=len, reverse=True):
            if any("\u4e00" <= char <= "\u9fff" for char in stop):
                value = value.replace(stop, "|")
        return {
            match.group(0)[index:index + 3]
            for match in re.finditer(r"[\u4e00-\u9fff]{3,}", value)
            for index in range(len(match.group(0)) - 2)
        }

    facet_cjk = _cjk_ngrams(facet_text)
    lowered_query = str(query or "").lower()
    query_ascii = set(re.findall(r"[a-z][a-z0-9_.+\-]*", lowered_query))
    query_cjk = _cjk_ngrams(lowered_query)
    anchors = {
        token for token in query_ascii
        if token not in _QUERY_STOP_WORDS and token not in facet_ascii
    } | {
        token for token in query_cjk
        if token not in _QUERY_STOP_WORDS and token not in facet_cjk
    }
    if not anchors:
        # A product-only query is not made answerable by generic product
        # overview paragraphs. Other explicit technical facets (for example
        # SPDP or QoS) may still be supported even when no extra prose anchor
        # remains after removing instructional words.
        facet_ids = [str(facet.get("id") or "") for facet in (required_facets or [])]
        if not facet_ids or all(re.search(r"(?:dds|sdk|product)$", facet_id, re.I) for facet_id in facet_ids):
            return False
        return bool(evidence)
    evidence_text = " ".join(_text(item).lower() for item in evidence)
    evidence_ascii = set(re.findall(r"[a-z][a-z0-9_.+\-]*", evidence_text))
    evidence_cjk = _cjk_ngrams(evidence_text)
    return bool(anchors & (evidence_ascii | evidence_cjk))


def _same_topic_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_section = re.sub(r"\b(c\+\+|cpp|java|c语言|c)\b", "", str(left.get("section") or "").lower())
    right_section = re.sub(r"\b(c\+\+|cpp|java|c语言|c)\b", "", str(right.get("section") or "").lower())
    if left_section and right_section and left_section == right_section:
        return True
    left_tokens, right_tokens = _tokens(_text(left)), _tokens(_text(right))
    return bool(left_tokens and right_tokens) and len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1) >= .82


def _facet(name: str, required: bool, terms: Iterable[str] = ()) -> dict[str, Any]:
    identity = facet_concept_identity(name)
    return {
        "id": name,
        "label": name,
        "terms": tuple(dict.fromkeys(value for value in (name, *terms) if value)),
        "required": required,
        "concept_id": identity,
        "semantic_identity": identity or name,
    }


def _required_facet_terms(name: str) -> tuple[str, ...]:
    """Expand an explicit compound/API name to its controlled aliases.

    User wording may name a concept such as ``history_depth`` while the
    manual uses ``HistoryQosPolicy`` or ``history``.  The facet remains
    identified by the user's term; aliases only improve evidence matching.
    """
    normalized = re.sub(r"[^a-z0-9]", "", str(name).lower())
    terms = [str(name)]
    for canonical, aliases in _FACET_ALIASES:
        canonical_normalized = re.sub(r"[^a-z0-9]", "", canonical.lower())
        alias_normalized = {
            re.sub(r"[^a-z0-9]", "", alias.lower()) for alias in aliases
        }
        if (
            normalized == canonical_normalized
            or normalized in alias_normalized
            or normalized.startswith(canonical_normalized + "_")
        ):
            terms.extend((canonical, *aliases))
    # Individual words in an unregistered compound/API/configuration name are
    # too weak to establish direct evidence.  For example,
    # ``SAMPLE_REJECTED`` must not be covered by a paragraph that only
    # mentions generic ``sample`` or ``rejected`` prose.  Retrieval keeps the
    # original rewritten query separately, so coverage terms remain exact.
    return tuple(dict.fromkeys(term for term in terms if term))


def extract_facet_requirements(query: str, rewritten: QueryRewrite | None = None) -> dict[str, list[dict[str, Any]]]:
    """Separate explicit requested facets from controlled retrieval expansions."""
    rewritten = rewritten or rewrite_query(query)
    required = [_facet(term, True, _required_facet_terms(term)[1:]) for term in rewritten.required_facets]
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
        "facet_diagnostics": dict(rewritten.facet_diagnostics or {
            "raw_extracted_facets": list(rewritten.technical_entities),
            "accepted_required_facets": [facet["id"] for facet in required],
            "rejected_noise_facets": [],
        }),
    }


def facets_for_candidate(item: dict[str, Any], facets: Iterable[dict[str, Any]]) -> set[str]:
    text = _text(item).lower()
    return {
        str(facet["id"])
        for facet in facets
        if any(_facet_term_matches(text, term) for term in facet.get("terms", ()) if term)
        and _concept_supported(item, facet)
    }


def _facet_term_matches(text: str, term: Any) -> bool:
    """Match an explicit technical identifier without broad keyword drift.

    Documentation commonly writes the same identifier as ``meta_traffic``
    or ``meta-traffic`` while the query facet is ``metatraffic``. Preserve the
    existing literal match, then allow a normalized match only when the
    candidate token has an explicit separator. This avoids turning short
    identifiers such as ``IP`` into arbitrary substring matches.
    """
    term_text = str(term or "").strip().lower()
    if not term_text or term_text in text:
        return bool(term_text)
    if not re.fullmatch(r"[a-z][a-z0-9_.+\- ]*", term_text):
        return False
    canonical_term = re.sub(r"[^a-z0-9]", "", term_text)
    if not canonical_term:
        return False
    for token in re.findall(r"[a-z][a-z0-9_.+\-_]*", text):
        if not re.search(r"[_\-\s]", token):
            continue
        canonical_token = re.sub(r"[^a-z0-9]", "", token)
        if canonical_token == canonical_term or canonical_token.startswith(canonical_term):
            return True
    return False


def facet_candidate_map(candidates: list[dict[str, Any]], facets: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    facet_list = list(facets)
    result = {str(facet["id"]): [] for facet in facet_list}
    for item in candidates:
        candidate_id = _candidate_id(item)
        for facet_id in facets_for_candidate(item, facet_list):
            if candidate_id:
                result[facet_id].append(candidate_id)
    return result


def build_required_facet_recovery_map(
    candidates: list[dict[str, Any]],
    required_facets: Iterable[dict[str, Any]],
    missing_facet_ids: Iterable[str],
) -> dict[str, list[str]]:
    """Return only validated candidate IDs for facets lost after selection.

    This deliberately reuses ``facets_for_candidate`` through
    ``facet_candidate_map``. It therefore cannot create support from a
    shared keyword alone: concept support and the existing facet evidence
    rules remain the authority. The input order is preserved so callers can
    choose a deterministic representative without introducing a new score
    policy.
    """
    wanted = {str(value) for value in missing_facet_ids}
    if not wanted:
        return {}
    coverage = facet_candidate_map(candidates, required_facets)
    return {
        facet_id: list(dict.fromkeys(candidate_ids))
        for facet_id, candidate_ids in coverage.items()
        if facet_id in wanted and candidate_ids
    }


_OFFER_WORDS = ("offered", "offer", "provide", "provides", "provided", "produce", "produces", "发布端", "提供", "产生", "生产", "写者配置", "数据写者配置")
_REQUEST_WORDS = ("requested", "request", "require", "requires", "consume", "consumes", "订阅端", "请求", "要求", "消费", "依赖", "读者配置", "数据读者配置")
_COMPAT_WORDS = ("compatible", "compatibility", "incompatible", "matching", "match", "r x o", "rxo", "兼容", "不兼容", "匹配", "相容", "满足")
_RULE_WORDS = ("rule", "ordering", "greater", "lower", "higher", "less", "大于", "小于", "高于", "低于", "规则")
_STATUS_WORDS = ("status", "callback", "listener", "incompatible", "状态", "回调", "监听")
_SUBJECT_ROLE_ALIASES = {
    "writer": ("writer", "datawriter", "写者", "发布端", "发布者", "发送端"),
    "reader": ("reader", "datareader", "读者", "订阅端", "订阅者", "接收端"),
}
# Relation objects are extracted from natural-language questions and can
# contain grammatical glue ("are", "their", "values", ...).  Keeping those
# words as required object terms makes a generic compatibility relation look
# unsupported even when the technical object is present in the evidence.
_RELATION_OBJECT_STOP_WORDS = {
    "a", "an", "and", "are", "be", "but", "can", "determine", "different",
    "differ", "discovered", "does", "for", "from", "has", "have", "in",
    "is", "must", "of", "on", "or", "side", "the", "their", "to", "under",
    "unsatisfied", "value", "values", "version", "versions", "whether", "with",
}

_GENERIC_OBJECT_TERMS = {
    "a", "an", "and", "are", "be", "but", "can", "constraint", "constraints",
    "configuration", "config", "determine", "different", "differ", "discovered",
    "does", "for", "from", "has", "have", "in", "is", "must", "of", "on", "or",
    "policy", "qos", "rule", "rules", "side", "the", "their", "to", "under",
    "unsatisfied", "value", "values", "version", "versions", "whether", "with",
}
_CONSTRAINT_RELATIONS = {
    "compatibility", "compatible", "matches", "satisfies", "requires", "depends",
    "upper_bound", "lower_bound", "version_compatibility", "configuration_constraint",
    "produces_constraint", "consumes_constraint",
}
_CONSTRAINT_TYPES = {
    "compatibility_rule", "comparison", "bound", "version_compatibility",
    "configuration_constraint", "produces_constraint", "consumes_constraint",
}


def _normalized_relation_label(value: Any) -> str:
    return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())


def _has_any(text: str, words: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _relation_object_terms(object_name: str) -> tuple[str, ...]:
    """Return technical anchors, excluding grammatical and generic QoS words."""
    tokens = [
        term.lower() for term in re.findall(
            r"[A-Za-z][A-Za-z0-9_.+\-]*|[\u4e00-\u9fff]{2,}", object_name
        )
        if term and term.lower() not in _RELATION_OBJECT_STOP_WORDS
    ]
    specific = [term for term in tokens if term not in _GENERIC_OBJECT_TERMS]
    return tuple(dict.fromkeys(specific or tokens))


def relation_requires_constraint(relation: dict[str, Any]) -> bool:
    """Whether presence alone cannot fully support this relation."""
    kind = _normalized_relation_label(relation.get("relation"))
    constraint_type = _normalized_relation_label(relation.get("constraint_type"))
    return constraint_type in _CONSTRAINT_TYPES or kind in _CONSTRAINT_RELATIONS


def _relation_object_matches(text: str, relation: dict[str, Any]) -> bool:
    terms = _relation_object_terms(str(relation.get("object") or ""))
    lowered = text.lower()
    # Every remaining technical anchor must occur in the same evidence item.
    # This prevents a generic QoS/RxO paragraph from borrowing support for a
    # different policy or configuration object.
    aliases = dict(_FACET_ALIASES)
    return bool(terms) and all(
        any(alias.lower() in lowered for alias in aliases.get(term, (term,)))
        for term in terms
    )


def _has_comparison_signal(text: str) -> bool:
    # Enriched markdown contains HTML fragments such as ``<br>``.  Their
    # closing ``>`` is formatting, not a comparison operator.  Strip tags
    # before looking for symbolic comparisons while preserving real prose
    # such as ``RELIABLE > BEST_EFFORT``.
    semantic_text = re.sub(r"<[^>]*>", " ", text)
    return bool(re.search(
        # Symbolic comparisons must have a token on both sides.  This
        # excludes markdown headings (``section > subsection``) and version
        # notes such as ``<2.2.5`` while retaining enum comparisons.
        r"(?:[A-Za-z_][A-Za-z0-9_.]*\s*(?:>=|<=|>|<)\s*[A-Za-z_][A-Za-z0-9_.]*|\b(?:greater|less|higher|lower|at\s+least|at\s+most|no\s+more|no\s+less)\b|大于|小于|高于|低于|不高于|不低于|至少|至多)",
        semantic_text,
        re.I,
    ))


def _constraint_anchor_text(text: str, relation: dict[str, Any], radius: int = 360) -> str:
    """Keep constraint checks local to the relation's technical object."""
    semantic_text = re.sub(r"<[^>]*>", " ", text)
    terms = _relation_object_terms(str(relation.get("object") or ""))
    aliases = dict(_FACET_ALIASES)
    windows = [
        semantic_text[max(0, match.start() - radius):match.end() + radius]
        for term in terms
        for alias in aliases.get(term, (term,))
        for match in re.finditer(re.escape(alias), semantic_text, re.I)
    ]
    return " ".join(windows) if windows else semantic_text


def _has_concrete_constraint_signal(text: str, relation: dict[str, Any]) -> bool:
    """Require a rule/comparison, not merely the words RxO/compatible."""
    # Do not let unrelated sections in a large log/table chunk create a false
    # rule signal.  The actual constraint must be local to this object's
    # technical anchor.
    semantic_text = _constraint_anchor_text(text, relation)
    lowered = semantic_text.lower()
    kind = _normalized_relation_label(relation.get("relation"))
    has_rule = _has_any(lowered, _RULE_WORDS + ("precedence", "satisfy", "satisfies", "satisfy", "must", "shall", "实际使用"))
    has_compatibility_table = "|" in semantic_text and _has_any(
        lowered, ("writer configuration", "reader configuration", "写者配置", "读者配置", "通信模式")
    )
    has_sides = (
        (_has_any(lowered, _OFFER_WORDS) and _has_any(lowered, _REQUEST_WORDS))
        or ("datawriter" in lowered and "datareader" in lowered)
        or ("写者" in lowered and "读者" in lowered)
        or (_has_any(lowered, ("producer", "publisher")) and _has_any(lowered, ("consumer", "subscriber")))
    )
    has_compatibility = _has_any(lowered, _COMPAT_WORDS)
    if _has_comparison_signal(lowered) and (
        has_compatibility
        or (_has_any(lowered, _OFFER_WORDS) and _has_any(lowered, _REQUEST_WORDS))
    ):
        return True
    # A compatibility relation needs an explicit compatibility signal.  A
    # Reliability/History behavior table is concrete evidence, but it is not
    # by itself the offered-vs-requested matching rule asked by the user.
    if has_sides and (has_rule or has_compatibility_table) and has_compatibility:
        return True
    if kind in {"upper_bound", "lower_bound"}:
        return has_rule and bool(re.search(r"\d|limit|threshold|上限|下限|阈值", lowered))
    if "configuration" in kind or "config" in kind:
        return has_rule and bool(re.search(r"set|configure|配置|设置|取值|value", lowered))
    return False


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
    object_hit = _relation_object_matches(text, relation)
    role_hit = _has_any(lowered, _OFFER_WORDS if kind in {"offers", "produces"} else _REQUEST_WORDS if kind in {"requests", "consumes", "depends"} else _COMPAT_WORDS)
    if kind in {"offers", "produces"}:
        supported = subject_hit and object_hit and _has_any(lowered, _OFFER_WORDS)
    elif kind in {"requests", "consumes", "depends"}:
        supported = subject_hit and object_hit and _has_any(lowered, _REQUEST_WORDS)
    elif kind in {"matches", "compatible", "satisfies"}:
        compat_hit = _has_any(lowered, _COMPAT_WORDS) or "matching rule" in lowered or "match rule" in lowered
        supported = object_hit and compat_hit and (
            subject_hit
            or (subject_hit and _has_any(lowered, _OFFER_WORDS + _REQUEST_WORDS))
            or (_has_any(lowered, _OFFER_WORDS) and _has_any(lowered, _REQUEST_WORDS))
            or ("datawriter" in lowered and "datareader" in lowered)
            or _has_any(lowered, _RULE_WORDS)
        )
    else:
        supported = subject_hit and role_hit
    if not supported:
        return None
    return {"evidence_id": _candidate_id(item), "relation": relation, "normalization": {"subject": subject, "relation": kind}}


def relation_constraint_support(item: dict[str, Any], relation: dict[str, Any]) -> dict[str, Any] | None:
    """Return support only when a relation's concrete rule is present.

    A compatibility label, RxO declaration, or incompatible status is useful
    presence evidence.  It is deliberately insufficient for a constraint
    relation unless the same item also contains a comparison/directional rule
    for the relation's own technical object.
    """
    if not relation_requires_constraint(relation):
        return None
    if not _relation_object_matches(_text(item), relation):
        return None
    if not _has_concrete_constraint_signal(_text(item), relation):
        return None
    return {
        "evidence_id": _candidate_id(item),
        "relation": relation,
        "normalization": {
            "subject": str(relation.get("subject") or "").lower(),
            "relation": str(relation.get("relation") or "").lower(),
            "coverage": "constraint",
        },
    }


def relation_support_strength(item: dict[str, Any], relation: dict[str, Any]) -> int:
    """Rank semantic evidence forms without naming a particular API/policy."""
    support = relation_constraint_support(item, relation) if relation_requires_constraint(relation) else relation_support(item, relation)
    if not support:
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
    if relation_requires_constraint(relation) and relation_constraint_support(item, relation):
        strength += 3
    if kind in {"matches", "compatible", "satisfies"} and _has_any(lowered, _RULE_WORDS):
        strength += 2
    if kind in {"matches", "compatible", "satisfies"}:
        if _has_any(lowered, _OFFER_WORDS) and _has_any(lowered, _REQUEST_WORDS):
            strength += 3
        if _has_any(lowered, ("通信模式", "communication mode", "通信模式匹配")):
            strength += 4
        if _has_any(lowered, ("reliable", "reliability", "可靠")) and _has_any(
            lowered, ("best_effort", "best-effort", "尽力而为")
        ):
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
    """Build one bounded query for missing presence or concrete constraints."""
    coverage = relation_coverage(candidates, relations)
    target_ids = coverage["recovery_target_relation_ids"]
    if not target_ids:
        return None
    terms = [query]
    for index in target_ids:
        relation = relations[int(index)]
        terms.extend((str(relation.get("subject") or ""), str(relation.get("relation") or "")))
        if index in coverage["missing_relation_constraints"]:
            terms.extend(coverage["recovery_target_constraints"].get(index, ()))
        else:
            terms.extend((str(relation.get("object") or ""), "presence"))
    return " ".join(dict.fromkeys(term for term in terms if term))


def build_facet_recovery_query(
    query: str,
    facets: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str | None:
    """Build one bounded query for explicit facets absent from retrieval.

    Facet recovery is deliberately generic: it uses the facet's own terms and
    does not add a product- or policy-specific branch.  The caller still
    limits the final evidence size; this function only improves recall.
    """
    present = facet_candidate_map(candidates, facets)
    missing = [facet for facet in facets if not present.get(str(facet.get("id")))]
    if not missing:
        return None
    terms = [query]
    for facet in missing:
        terms.extend(str(term) for term in facet.get("terms", ()) if term)
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
    relation_coverage_data = relation_coverage(evidence, relation_facets)
    relation_covered = relation_coverage_data["covered_relation_facets"]
    relation_evidence_ids = [relation_supporting[key] for key in relation_covered]
    relation_chain = len(relation_covered) == len(relation_facets) and len(set().union(*map(set, relation_evidence_ids))) >= 2 if relation_facets else False
    strength = evidence_strength_summary(evidence, required_facets, relation_facets)
    if compositional and strength.get("overall") == "unsupported":
        strength["overall"] = "supported_inference"
    return {
        "directly_covered_facets": direct,
        "compositionally_covered_facets": compositional,
        "unsupported_facets": unsupported,
        "facet_supporting_evidence_ids": supporting,
        "reasoning_links": [{"relation": relation, "evidence_ids": ids} for relation, ids in relation_ids.items() if ids],
        "covered_relation_facets": relation_covered,
        "uncovered_relation_facets": relation_coverage_data["uncovered_relation_facets"],
        "relation_supporting_evidence_ids": relation_supporting,
        "relation_presence_covered": relation_coverage_data["relation_presence_covered"],
        "relation_constraint_covered": relation_coverage_data["relation_constraint_covered"],
        "presence_support_ids": relation_coverage_data["presence_support_ids"],
        "constraint_support_ids": relation_coverage_data["constraint_support_ids"],
        "missing_relation_constraints": relation_coverage_data["missing_relation_constraints"],
        "incomplete_relations": relation_coverage_data["incomplete_relations"],
        "recovery_target_relation_ids": relation_coverage_data["recovery_target_relation_ids"],
        "recovery_target_constraints": relation_coverage_data["recovery_target_constraints"],
        "relation_diagnostics": relation_coverage_data["relation_diagnostics"],
        "relation_chain_supported": relation_chain,
        "semantic_normalization": [{"relation_index": key, "evidence_ids": ids} for key, ids in relation_supporting.items() if ids],
        "evidence_strength": strength,
        "semantic_concept_conflicts": semantic_concept_conflicts(query, evidence, required_facets),
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
        result["relation_presence_stages"] = result["relation_stages"]
        result["relation_constraint_stages"] = {
            stage: relation_constraint_candidate_map(items, relation_facets)
            for stage, items in stages.items()
        }
        result["relation_first_seen_stage"] = {
            str(index): next((stage for stage in ordered if relation_candidate_map(stages[stage], [relation])["0"]), None)
            for index, relation in enumerate(relation_facets)
        }
        result["relation_first_lost_stage"] = {}
        for index, relation in enumerate(relation_facets):
            relation_id = str(index)
            seen = False
            lost = None
            for stage in ordered:
                if result["relation_stages"][stage][relation_id]:
                    seen = True
                elif seen:
                    lost = stage
                    break
            result["relation_first_lost_stage"][relation_id] = lost
        result["relation_constraint_first_seen_stage"] = {
            str(index): next(
                (stage for stage in ordered if result["relation_constraint_stages"][stage][str(index)]),
                None,
            )
            for index in range(len(relation_facets))
        }
    if "evidence" in stages:
        result.update(analyze_evidence_support("", stages["evidence"], required_facets, relation_facets))
    return result


def _candidate_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Stable fallback key used whenever candidates tie semantically."""
    return (
        -float(item.get("rerank_score", 0) or 0),
        -float(item.get("fusion_score", 0) or 0),
        str(item.get("source_file") or ""),
        str(item.get("section") or ""),
        _candidate_id(item),
        _text(item),
    )


def _target_sort_key(value: str) -> tuple[int, int | str]:
    prefix, _, suffix = str(value).partition(":")
    try:
        number: int | str = int(suffix)
    except ValueError:
        number = suffix
    return (0 if prefix == "relation" else 1, number)


def select_evidence(
    query: str,
    candidates: list[dict[str, Any]],
    top_n: int = 5,
    *,
    requirements: dict[str, list[dict[str, Any]]] | None = None,
    force_relation_ids: Iterable[str] = (),
    force_facet_ids: Iterable[str] = (),
    preferred_candidate_ids: Iterable[str] = (),
    recovery_support_map: dict[str, list[str]] | None = None,
    required_recovery_evidence_ids: Iterable[str] = (),
    required_recovery_target_map: dict[str, list[str]] | None = None,
    required_constraint_support_ids: Iterable[str] = (),
    selection_run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Select deterministic final evidence with reserved recovery coverage.

    Validated recovery candidates are selected in a dedicated phase.  They do
    not re-enter the ordinary score competition, while ordinary candidates
    still fill the remaining slots and cover other required facets/relations.
    """
    if not candidates or top_n <= 0:
        return []
    requirements = requirements or extract_facet_requirements(query)
    required, auxiliary = requirements["required_facets"], requirements["auxiliary_facets"]
    relations = requirements.get("required_relation_facets", requirements.get("relation_facets", []))
    forced = {str(value) for value in force_relation_ids}
    forced_facets = {str(value) for value in force_facet_ids}
    preferred = {str(value) for value in preferred_candidate_ids}
    recovery_support_map = {str(key): list(dict.fromkeys(str(value) for value in values or [])) for key, values in (recovery_support_map or {}).items()}
    recovery_target_map = {
        str(key): list(dict.fromkeys(str(value) for value in values or []))
        for key, values in (required_recovery_target_map or recovery_support_map).items()
    }
    required_recovery_ids = {str(value) for value in required_recovery_evidence_ids}
    required_constraint_ids = {str(value) for value in required_constraint_support_ids}
    if not required_recovery_ids:
        # Backwards-compatible callers still get reserved representatives: one
        # deterministic validated candidate per recovery target.
        for target, ids in sorted(recovery_target_map.items(), key=lambda pair: _target_sort_key(pair[0])):
            if ids:
                required_recovery_ids.add(sorted(ids)[0])

    run_id = selection_run_id or str(uuid4())
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[Any, ...]] = set()
    selected_reasons: dict[int, str] = {}
    covered: set[str] = set()
    covered_relations: set[str] = set()
    target_reasons: dict[str, str] = {}

    def item_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            str(item.get("_dedup_key") or ""),
            str(item.get("source_file") or ""),
            str(item.get("section") or ""),
            _candidate_id(item),
            _text(item),
        )

    def add(item: dict[str, Any], reason: str, gains: set[str] = set()) -> None:
        key = item_key(item)
        if key in selected_keys or len(selected) >= top_n:
            return
        if item in remaining:
            remaining.remove(item)
        selected_keys.add(key)
        selected.append(item)
        selected_reasons[id(item)] = reason
        for target in gains:
            target_reasons[target] = reason

    def relation_gains(item: dict[str, Any], only: set[str] | None = None) -> set[str]:
        gains: set[str] = set()
        for index, relation in enumerate(relations):
            relation_id = str(index)
            if relation_id in covered_relations or (only is not None and relation_id not in only):
                continue
            use_constraint = relation_requires_constraint(relation) and any(
                relation_constraint_support(other, relation) for other in [item, *remaining]
            )
            support = relation_constraint_support(item, relation) if use_constraint else relation_support(item, relation)
            if support:
                gains.add(f"relation:{relation_id}")
        return gains

    def mark_gains(gains: set[str]) -> None:
        for target in gains:
            if target.startswith("relation:"):
                covered_relations.add(target.split(":", 1)[1])
            else:
                covered.add(target)

    # Phase 1: reserve one validated Recovery representative per missing
    # target.  A single item can satisfy several targets and consumes one slot.
    recovery_candidate_ids = {
        candidate_id
        for candidate_ids in recovery_target_map.values()
        for candidate_id in candidate_ids
    }
    recovery_items = [
        item for item in remaining
        if _candidate_id(item) in required_recovery_ids
        and (
            item.get("recovery_retrieval")
            or not recovery_target_map
            or _candidate_id(item) in recovery_candidate_ids
        )
    ]
    while recovery_items and len(selected) < top_n:
        eligible: list[tuple[dict[str, Any], set[str]]] = []
        for item in recovery_items:
            gains = set()
            for target, ids in recovery_target_map.items():
                if _candidate_id(item) not in ids or target in target_reasons:
                    continue
                if target.isdigit() and int(target) < len(relations):
                    if relation_constraint_support(item, relations[int(target)]):
                        gains.add(f"relation:{target}")
                elif target.startswith("relation:") and target[9:].isdigit() and int(target[9:]) < len(relations):
                    if relation_constraint_support(item, relations[int(target[9:])]):
                        gains.add(target)
                elif target in facets_for_candidate(item, required):
                    gains.add(target)
            if gains:
                eligible.append((item, gains))
        if not eligible:
            break
        best, gains = min(eligible, key=lambda pair: (-len(pair[1]), _candidate_sort_key(pair[0])))
        add(best, "required_constraint" if any(g.startswith("relation:") for g in gains) else "required_recovery", gains)
        mark_gains(gains)
        recovery_items = [item for item in recovery_items if item is not best]

    # Phase 1b: reserve concrete constraint evidence that was already found
    # in the ordinary retrieval pass.  It is answer-critical just like a
    # recovery hit, but it is not necessarily marked as recovery retrieval.
    constraint_items = [
        item for item in remaining
        if _candidate_id(item) in required_constraint_ids
    ]
    while constraint_items and len(selected) < top_n:
        eligible: list[tuple[dict[str, Any], set[str], int]] = []
        for item in constraint_items:
            gains: set[str] = set()
            strength = 0
            for index, relation in enumerate(relations):
                relation_id = str(index)
                if relation_id in covered_relations:
                    continue
                support = relation_constraint_support(item, relation)
                if support:
                    gains.add(f"relation:{relation_id}")
                    strength = max(strength, relation_support_strength(item, relation))
            if gains:
                eligible.append((item, gains, strength))
        if not eligible:
            break
        best, gains, _strength = max(
            eligible,
            key=lambda pair: (
                len(pair[1]),
                pair[2],
                float(pair[0].get("rerank_score", 0) or pair[0].get("fusion_score", 0) or 0),
                tuple(-ord(char) for char in _candidate_id(pair[0])[:32]),
            ),
        )
        add(best, "required_constraint", gains)
        mark_gains(gains)
        constraint_items = [item for item in constraint_items if item is not best]

    # Phase 2: cover remaining required relations, preferring validated
    # constraint support whenever that relation requires a concrete rule.
    while remaining and len(selected) < top_n and relations:
        eligible = [(item, relation_gains(item)) for item in remaining]
        eligible = [(item, gains) for item, gains in eligible if gains]
        if not eligible:
            break
        best, gains = min(eligible, key=lambda pair: (-len(pair[1]), -int(_candidate_id(pair[0]) in preferred), _candidate_sort_key(pair[0])))
        add(best, "required_relation", gains)
        mark_gains(gains)

    # Phase 3: cover required facets without allowing a recovery item to
    # evict a relation/side already reserved above.
    while remaining and len(selected) < top_n:
        eligible = [(item, facets_for_candidate(item, required) - covered) for item in remaining]
        eligible = [(item, gains) for item, gains in eligible if gains]
        if not eligible:
            break
        best, gains = min(eligible, key=lambda pair: (-len(pair[1]), -int(_candidate_id(pair[0]) in preferred), _candidate_sort_key(pair[0])))
        add(best, "required_facet", gains)
        mark_gains(gains)

    # Phase 4: relevance fill only after all hard target phases. For a
    # multi-facet diagnostic request, stop once every required facet is
    # represented. Extra lexical hits can be valid documents yet still be
    # unrelated remediation material (for example a CPU-affinity paragraph
    # that happens to repeat ``usertraffic``). They must not be handed to the
    # generator merely to pad Top-N.
    required_ids = {str(facet.get("id") or "") for facet in required}
    query_terms, requested_language = _tokens(query), _language(query)
    network_diagnostic = bool(_NETWORK_DIAGNOSTIC_RE.search(str(query or ""))) and not _PERFORMANCE_INTENT_RE.search(str(query or ""))
    if not network_diagnostic or not required_ids or covered != required_ids:
        while remaining and len(selected) < top_n:
            def key(item: dict[str, Any]) -> tuple[Any, ...]:
                duplicate = any(_same_topic_group(item, chosen) for chosen in selected)
                language_exception = requested_language != "generic" and _language(_text(item)) == requested_language
                score = float(item.get("rerank_score", 0) or 0)
                overlap = float(len(query_terms & _tokens(_text(item))))
                return (-score - .015 * len(facets_for_candidate(item, auxiliary)) - .001 * overlap + (.12 if duplicate and not language_exception else 0), _candidate_sort_key(item))
            add(min(remaining, key=key), "relevance_fill")

    lexical_uncovered = {str(facet["id"]) for facet in required} - covered
    support = analyze_evidence_support(query, selected, required, relations)
    required_targets_before = sorted(
        {f"facet:{facet['id']}" for facet in required}
        | {f"relation:{index}" for index in range(len(relations))},
        key=_target_sort_key,
    )
    required_targets_after = sorted(
        {f"facet:{facet['id']}" for facet in required if str(facet["id"]) not in lexical_uncovered}
        | {f"relation:{index}" for index in support.get("covered_relation_facets", [])},
        key=_target_sort_key,
    )
    lost_required_targets = [target for target in required_targets_before if target not in required_targets_after]
    for rank, item in enumerate(selected, 1):
        item["evidence_rank"] = rank
        item["evidence_facets"] = sorted(facets_for_candidate(item, required + auxiliary))
        item["required_facets"] = [facet["id"] for facet in required]
        item["covered_facets"] = sorted(covered)
        item["uncovered_facets"] = sorted(lexical_uncovered)
        item["covered_relation_facets"] = support.get("covered_relation_facets", [])
        item["uncovered_relation_facets"] = support.get("uncovered_relation_facets", [])
        item["recovery_support_map"] = recovery_support_map
        item["selection_run_id"] = run_id
        item["candidate_priority_class"] = (
            "required_recovery" if _candidate_id(item) in required_recovery_ids
            else "required_constraint" if _candidate_id(item) in required_constraint_ids
            else "required_target" if selected_reasons.get(id(item), "").startswith("required_")
            else "relevance_fill"
        )
        item["candidate_score"] = float(item.get("rerank_score", 0) or item.get("fusion_score", 0) or 0)
        item["candidate_targets_supported"] = sorted(
            set(f"facet:{value}" for value in facets_for_candidate(item, required))
            | {
                f"relation:{index}"
                for index, relation in enumerate(relations)
                if (
                    relation_constraint_support(item, relation)
                    if relation_requires_constraint(relation)
                    else relation_support(item, relation)
                )
            },
            key=_target_sort_key,
        )
        item["selection_reason"] = selected_reasons.get(id(item), "relevance_fill")
        item["required_recovery_evidence_ids"] = sorted(required_recovery_ids)
        item["required_recovery_target_map"] = recovery_target_map
        item["required_constraint_support_ids"] = sorted(required_constraint_ids or {
            value for values in recovery_target_map.values() for value in values
        })
        item["required_targets_before_selection"] = required_targets_before
        item["required_targets_after_selection"] = required_targets_after
        item["lost_required_targets_after_selection"] = lost_required_targets
        item.update(support)
        item["scenario_terms"] = sorted(term for term in _SCENARIO_ALIASES if term in query.lower())
    return selected


def evidence_target_signature(
    evidence: list[dict[str, Any]],
    requirements: dict[str, list[dict[str, Any]]],
    *,
    facet_ids: Iterable[str] = (),
    relation_ids: Iterable[str] = (),
) -> dict[str, tuple[str, ...]]:
    """Return only the support relevant to the current validation targets.

    Comparing whole Top-N lists makes an unrelated rank change look like a
    useful retry.  Comparing this signature makes retry decisions semantic:
    the evidence supporting the missing facet/relation must change.
    """
    required = requirements.get("required_facets", [])
    relations = requirements.get("required_relation_facets", requirements.get("relation_facets", []))
    wanted_facets = {str(value) for value in facet_ids}
    wanted_relations = {str(value).removeprefix("relation:") for value in relation_ids}
    result: dict[str, tuple[str, ...]] = {}
    for facet in required:
        facet_id = str(facet.get("id") or "")
        if facet_id in wanted_facets:
            result[f"facet:{facet_id}"] = tuple(sorted(
                _candidate_id(item) for item in evidence
                if facet_id in facets_for_candidate(item, [facet])
            ))
    for index, relation in enumerate(relations):
        relation_id = str(index)
        if relation_id in wanted_relations:
            result[f"relation:{relation_id}"] = tuple(sorted(
                _candidate_id(item) for item in evidence
                if (relation_constraint_support(item, relation) if relation_requires_constraint(relation) else relation_support(item, relation))
            ))
    return result


def relation_constraint_candidate_map(candidates: list[dict[str, Any]], relations: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    result = {str(index): [] for index, _ in enumerate(relations)}
    for index, relation in enumerate(relations):
        for item in candidates:
            if relation_constraint_support(item, relation):
                result[str(index)].append(_candidate_id(item))
    return result


def relation_coverage(candidates: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute presence and concrete-constraint support independently."""
    presence = relation_candidate_map(candidates, relations)
    constraints = relation_constraint_candidate_map(candidates, relations)
    presence_covered = [key for key, ids in presence.items() if ids]
    constraint_covered = [
        str(key) for key, relation in enumerate(relations)
        if (not relation_requires_constraint(relation) and presence.get(str(key))) or constraints.get(str(key))
    ]
    incomplete = [
        str(index) for index, relation in enumerate(relations)
        if presence.get(str(index)) and relation_requires_constraint(relation) and not constraints.get(str(index))
    ]
    fully_covered = [
        str(index) for index, relation in enumerate(relations)
        if presence.get(str(index)) and (not relation_requires_constraint(relation) or constraints.get(str(index)))
    ]
    missing_presence = [str(index) for index in range(len(relations)) if not presence.get(str(index))]
    missing_constraints = [
        str(index) for index, relation in enumerate(relations)
        if relation_requires_constraint(relation) and not constraints.get(str(index))
    ]
    relation_diagnostics = [
        {
            "relation_id": str(index),
            "relation_subject": relation.get("subject"),
            "relation_object": relation.get("object"),
            "relation_presence_covered": bool(presence.get(str(index))),
            "relation_constraint_covered": str(index) in constraint_covered,
            "presence_support_ids": presence.get(str(index), []),
            "constraint_support_ids": constraints.get(str(index), []),
        }
        for index, relation in enumerate(relations)
    ]
    return {
        "presence_support_ids": presence,
        "constraint_support_ids": constraints,
        "relation_presence_covered": presence_covered,
        "relation_constraint_covered": constraint_covered,
        "covered_relation_facets": fully_covered,
        "uncovered_relation_facets": sorted(set(missing_presence + incomplete), key=int),
        "missing_relation_constraints": missing_constraints,
        "incomplete_relations": incomplete,
        "recovery_target_relation_ids": sorted(set(missing_presence + missing_constraints), key=int),
        "relation_diagnostics": relation_diagnostics,
        "recovery_target_constraints": {
            str(index): _constraint_target_terms(relation)
            for index, relation in enumerate(relations)
            if str(index) in set(missing_constraints)
        },
    }


def _constraint_target_terms(relation: dict[str, Any]) -> tuple[str, ...]:
    """Generate bounded, relation-driven recovery terms without policy names."""
    kind = _normalized_relation_label(relation.get("relation"))
    terms = [str(relation.get("object") or ""), "constraint", "rule", "comparison"]
    if kind in {"matches", "compatible", "satisfies"}:
        terms.extend(("compatibility", "RxO", "ordering", "precedence", "offered", "requested", "lower", "higher"))
    elif kind in {"upper_bound", "lower_bound"}:
        terms.extend(("upper bound", "lower bound", "limit", "threshold", "comparison"))
    elif "version" in kind:
        terms.extend(("version", "compatibility", "comparison"))
    elif "config" in kind:
        terms.extend(("configuration", "set", "value", "must"))
    else:
        terms.extend((kind, "required", "depends"))
    return tuple(dict.fromkeys(term for term in terms if term))


def effective_evidence_changed(
    first: list[dict[str, Any]],
    retry: list[dict[str, Any]],
    requirements: dict[str, list[dict[str, Any]]],
    *,
    facet_ids: Iterable[str] = (),
    relation_ids: Iterable[str] = (),
) -> bool:
    """Whether retry changed evidence relevant to unresolved targets."""
    return evidence_target_signature(
        first, requirements, facet_ids=facet_ids, relation_ids=relation_ids
    ) != evidence_target_signature(
        retry, requirements, facet_ids=facet_ids, relation_ids=relation_ids
    )
