"""Controlled, deterministic expansion from user wording to DDS terminology."""

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class QueryRewrite:
    original_query: str
    core_terms: tuple[str, ...] = ()
    technical_entities: tuple[str, ...] = ()
    scenario_terms: tuple[str, ...] = ()
    expansion_terms: tuple[str, ...] = ()
    required_facets: tuple[str, ...] = ()
    relation_facets: tuple[dict, ...] = ()
    facet_diagnostics: dict = field(default_factory=dict)

    @property
    def original(self) -> str:
        return self.original_query

    @property
    def terms(self) -> tuple[str, ...]:
        return self.core_terms + self.technical_entities + self.scenario_terms + self.expansion_terms

    @property
    def search_query(self) -> str:
        return " ".join((self.original_query, *self.core_terms, *self.scenario_terms,
                          *self.technical_entities, *self.expansion_terms))


_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("更新一次", "周期性更新", "截止期限", "deadline"),
     ("DeadlineQosPolicy", "deadline", "period", "RequestedDeadlineMissed", "OfferedDeadlineMissed")),
    (("发布端异常", "异常时订阅端", "感知", "存活性", "活性", "liveliness"),
     ("LivelinessQosPolicy", "liveliness", "lease_duration", "LIVELINESS_CHANGED_STATUS")),
    (("端序", "大小端", "endianness", "little endian", "big endian"),
     ("rtps_message_little_endian", "endianness", "serialization", "IDL", "type")),
    (("分片", "DATAFRAG", "NACKFRAG", "fragment"),
     ("fragmentation", "DataFrag", "NackFrag", "reassembly")),
    (("可靠重传", "重传", "retransmission"),
     ("reliable", "ReliabilityQosPolicy", "Heartbeat", "AckNack", "NackFrag")),
    (("资源限制", "资源上限", "resource limit"),
     ("ResourceLimitsQosPolicy", "resource_limits", "max_samples", "max_samples_per_instance")),
    (("阻塞等待", "多个dds状态", "多个 DDS 状态"),
     ("WaitSet", "Condition", "StatusCondition", "wait", "同步等待")),
    (("topic一样", "topic名字一样", "topic 名字一样", "相同 topic", "topic 名称", "收不到数据", "无法通信", "不匹配"),
     ("收不到数据", "故障排查", "配置检测", "Domain", "Domain ID", "Topic", "Type", "QoS", "Partition", "match", "匹配")),
    (("重复读取", "反复读取", "read以后", "read 以后", "同一批数据", "样本状态",
      "sample state", "samplestate", "return_loan"),
     ("read", "take", "take_next_sample", "SampleStateKind", "READ_SAMPLE_STATE",
      "NOT_READ_SAMPLE_STATE", "sample_state", "READ", "NOT_READ",
      "act of reading sample sets sample_state READ",
      "act of taking sample removes it from DataReader", "return_loan")),
    (("内容过滤", "过滤主题", "content filter"),
     ("ContentFilteredTopic", "filter_expression", "parameter")),
    (("idl", "结构体", "生成文件", "只替换", "新增成员"),
     ("IDL", "ZRDDS", "生成文件", "生成文件一致性", "内部结构不同", "zrddsgen", "类型一致", "类型不一致", "序列化", "反序列化")),
    (("listener", "监听器", "data_available", "回调", "死锁"),
     ("DataReader", "Listener", "DATA_AVAILABLE", "on_data_available", "回调限制", "死锁")),
)

# Cross-language vocabulary bridges. The local corpus contains both API
# terminology and Chinese manual terminology; retaining both sides of an
# explicit technical term improves recall without changing required facets.
_TERM_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("reliability", "reliable", "best_effort", "可靠性", "可靠", "尽力而为"),
     ("ReliabilityQosPolicy", "Reliable", "Best-effort", "可靠性", "可靠", "尽力而为")),
    (("writer", "datawriter", "数据写者", "发布端"),
     ("DataWriter", "数据写者", "发布端", "写者配置")),
    (("reader", "datareader", "数据读者", "订阅端"),
     ("DataReader", "数据读者", "订阅端", "读者配置")),
    (("qos", "服务质量"), ("QoS", "服务质量")),
    (("offered", "offer", "提供", "发布端"), ("offered QoS", "提供")),
    (("requested", "request", "请求", "订阅端"), ("requested QoS", "请求")),
)


_TECHNICAL_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*")
_LIST_SEPARATORS_RE = re.compile(r"[、,/，；;]|\b(?:and|or|vs)\b|(?:与|和|及|以及|并且)", re.I)
_NON_FACET_ENTITIES = {"compare", "explain", "describe", "how", "does", "what", "which", "the", "and", "or", "with", "from", "for", "work", "works", "must", "on", "to", "by", "who", "why", "where", "when", "match", "matches", "offer", "offers", "offered", "provide", "provides", "provided", "produce", "produces", "request", "requests", "requested", "require", "requires", "consume", "consumes", "compatible", "compatibility"}
_ENGLISH_FUNCTION_WORDS = {
    "a", "an", "are", "be", "been", "being", "but", "can", "could", "did",
    "do", "doing", "done", "each", "either", "else", "has", "have", "having",
    "if", "in", "is", "it", "its", "may", "might", "neither", "nor", "not",
    "of", "off", "onto", "only", "otherwise", "per", "rather", "same", "shall",
    "should", "so", "some", "than", "that", "their", "then", "there", "these",
    "those", "through", "under", "until", "very", "was", "were", "whether", "will",
    "would", "yet", "values", "value", "differ", "different", "discovered", "determine",
    "side", "unsatisfied", "incompatible", "discovered",
}
_RELATION_WORDS = {
    "offer", "offers", "offered", "provide", "provides", "provided", "produce", "produces",
    "request", "requests", "requested", "require", "requires", "required", "consume", "consumes",
    "depend", "depends", "dependent", "compatible", "compatibility", "matching", "match",
}
_KNOWN_TECHNICAL_WORDS = {
    "dds", "qos", "api", "idl", "topic", "type", "domain", "partition", "reader", "writer",
    "publisher", "subscriber", "participant", "datareader", "datawriter", "sample", "sampleinfo",
    "instance", "listener", "condition", "readcondition", "statuscondition", "querycondition",
    "reliability", "history", "deadline", "liveliness", "durability", "resource_limits", "resourcelimits",
    "serialization", "deserialization", "read", "take", "waitset", "policy", "status", "state",
}
# Explicit transport vocabulary is accepted as a facet when it appears in the
# user's question.  This is a controlled vocabulary check, not a case-specific
# answer or validator branch.
_CONTROLLED_FACET_ALIASES = (
    ("metatraffic", "meta traffic"),
    ("usertraffic", "user traffic"),
    ("discovery", "discovery"),
)


def _entity_facet_classification(original: str, entities: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[dict, ...]]:
    """Classify raw entity tokens before they become answer-critical facets.

    This is intentionally pattern/context based rather than a question-level
    blacklist.  Weak lexical candidates remain available in
    ``technical_entities`` for retrieval, while only high-confidence tokens
    become required facets.
    """
    lowered = original.lower()
    idl_context = bool(re.search(r"\b(?:idl|generated|generated\s+code|struct|schema)\b|结构体|生成文件", lowered, re.I))
    # A lower-case token is not automatically a required facet: ordinary
    # prose contains many such tokens. It becomes technical when it is one
    # side of an explicit list/pair (for example ``metatraffic and
    # usertraffic``), which is a language-independent structural signal.
    listed_entities = {
        match.group(index)
        for match in re.finditer(
            r"([A-Za-z][A-Za-z0-9_.+\-]*)\s*(?:[/、,，；;]|\band\b|\bor\b|与|和|及|以及|并且)\s*([A-Za-z][A-Za-z0-9_.+\-]*)",
            original,
            re.I,
        )
        for index in (1, 2)
    }
    accepted: list[str] = []
    rejected: list[dict] = []
    for entity in entities:
        value = entity.strip(".,:;!?()[]{}")
        token = value.lower()
        reason = None
        if not value:
            reason = "empty"
        elif token in _NON_FACET_ENTITIES or token in _ENGLISH_FUNCTION_WORDS:
            reason = "syntactic_fragment"
        elif token in _RELATION_WORDS:
            reason = "relation_word"
        elif any(token == name.lower() or token == alias.lower() for name, alias in _CONTROLLED_FACET_ALIASES):
            accepted.append(value)
            continue
        elif token in _KNOWN_TECHNICAL_WORDS:
            accepted.append(value)
            continue
        elif value in listed_entities and token not in _NON_FACET_ENTITIES and token not in _ENGLISH_FUNCTION_WORDS:
            accepted.append(value)
            continue
        elif re.fullmatch(r"v?\d+(?:\.\d+){1,3}", token, re.I):
            # A requested version is metadata used by version filtering, not
            # an answer facet that must occur in every evidence paragraph.
            reason = "version_metadata"
        elif re.search(r"[_\.]|\d", value) or (len(value) >= 2 and value.isupper()):
            accepted.append(value)
            continue
        elif re.search(r"[A-Z].*[A-Z]", value[1:]) or re.search(r"[a-z][A-Z]", value):
            accepted.append(value)
            continue
        elif re.search(r"(?:api|qos|policy|status|state|kind|condition|topic|reader|writer|publisher|subscriber|participant|type|mode|timeout|size|limit|session|buffer)$", token, re.I):
            accepted.append(value)
            continue
        elif re.search(r"\b(?:writer|reader|producer|consumer|publisher|subscriber)\b", token):
            accepted.append(value)
            continue
        elif idl_context and value[:1].isupper() and value[1:].islower() and len(value) >= 2:
            # Code symbols such as ``Foo`` are meaningful in an IDL/code
            # change question even without CamelCase or an underscore.
            accepted.append(value)
            continue
        else:
            reason = "low_confidence"
        rejected.append({"facet": value, "reason": reason or "non_technical"})
    return tuple(dict.fromkeys(accepted)), tuple(rejected)


def _relation_facets(original: str, entities: tuple[str, ...]) -> tuple[dict, ...]:
    """Extract role/constraint relations without using product vocabularies.

    The extractor deliberately records roles and constraints, not a list of
    known DDS policies.  This lets the evidence layer match equivalent
    producer/consumer and offered/requested wording across languages.
    """
    text = original.lower()
    if not re.search(r"(?:offer|offered|request|requested|provide|provides|produce|consume|require|depend|compatible|match|satisf(?:y|ies)|满足|提供|产生|请求|要求|依赖|兼容|匹配|不满足|规则|判断)", text, re.I):
        return ()
    clean_entities = [e for e in entities if e.lower() not in _NON_FACET_ENTITIES]
    subjects = [e for e in clean_entities if re.search(r"writer|reader|producer|consumer|publisher|subscriber", e, re.I)]
    for match in re.finditer(r"([A-Za-z][A-Za-z0-9_.+\-]*)\s+(?:offers?|provides?|produces?|requests?|requires?|consumes?|depends?)\b", original, re.I):
        if match.group(1) not in subjects:
            subjects.append(match.group(1))
    objects = [e for e in clean_entities if e not in subjects and e.lower() not in _NON_FACET_ENTITIES]
    obj = " ".join(objects) if objects else "the shared capability"
    relations: list[dict] = []
    # Role nouns such as ``发布端``/``订阅端`` describe topology, not an
    # offered/requested QoS relation. Require a verb or an explicit English
    # offered/requested form here.
    offer_words = bool(re.search(r"offered|offer|provide|provides|produce|提供|产生|生产|发布(?!端)", text, re.I))
    request_words = bool(re.search(r"requested|request|require|consume|请求|要求|消费|依赖|订阅(?!端)", text, re.I))
    if subjects and offer_words:
        relations.append({"subject": subjects[0], "relation": "offers", "object": obj, "constraint_type": "role", "required": True})
    if len(subjects) > 1 and request_words:
        relations.append({"subject": subjects[1], "relation": "requests", "object": obj, "constraint_type": "role", "required": True})
    # ``match`` in a diagnostic question may describe a protocol stage, not
    # a QoS ordering rule. Only explicit compatibility language or an
    # offered/requested pair creates a concrete compatibility relation.
    explicit_compatibility = bool(re.search(
        r"兼容|不兼容|相容|compatib(?:le|ility)|incompatib|r\s*x\s*o|rxo|satisf(?:y|ies)",
        text,
        re.I,
    ))
    if (offer_words and request_words) or explicit_compatibility:
        relations.append({"subject": subjects[0] if subjects else "producer", "relation": "matches", "object": obj, "constraint_type": "compatibility_rule", "required": True})
    return tuple(dict.fromkeys((tuple(sorted(item.items())) for item in relations)))


def _explicit_required_facets(original: str, entities: tuple[str, ...]) -> tuple[str, ...]:
    """Keep user-requested technical directions separate from retrieval hints.

    This intentionally uses syntax and exact entities rather than a DDS term
    list, so new vocabularies and mixed-language questions follow the same
    path.  A single explicit entity is also a required facet; that keeps the
    representation uniform for single-facet questions.
    """
    facets: list[str] = list(entities)
    lowered = original.lower()
    # Infer answer-critical facets from semantic signals when the user uses
    # Chinese prose instead of the canonical policy name. These are bounded
    # vocabulary bridges, not question-specific answer branches.
    semantic_facets = (
        (("更新一次", "周期性更新", "截止期限", "deadline"), "DeadlineQosPolicy"),
        (("发布端异常", "异常时订阅端", "感知", "存活性", "活性", "liveliness"), "LivelinessQosPolicy"),
        (("端序", "大小端", "endianness", "little endian", "big endian"), "rtps_message_little_endian"),
        (("分片", "fragment", "datafrag", "nackfrag"), "fragmentation"),
        (("可靠重传", "重传", "retransmission"), "reliable_retransmission"),
        (("资源限制", "资源上限", "resource limit"), "resource_limits"),
        (("entity lifecycle", "实体生命周期", "实体创建与删除", "create_topic", "delete_contained_entities"), "entity_lifecycle"),
        (("reader data lifecycle", "readerdatalifecycle", "reader data lifecycle qos"), "ReaderDataLifecycleQosPolicy"),
        (("sysctl.global.", "zrdds sysctl", "ZRDDS sysctl"), "sysctl.global.*"),
        (("linux sysctl", "内核 sysctl", "/proc/sys", "ethtool"), "linux_sysctl"),
        (("discovery", "发现地址", "发现阶段", "发现协议"), "discovery"),
        (("standard DDS API", "DDS 标准接口", "标准 DDS 接口"), "standard_dds_api"),
        (("ZRDDS extension", "扩展接口", "简化接口", "DDSIF"), "zrdds_extension_api"),
        (("使能后不可修改", "实体使能后不可修改", "cannot be changed after an entity is enabled", "enabled after", "immutable qos", "immutable policy", "不可变qos"), "qos_mutability"),
    )
    for triggers, facet in semantic_facets:
        if any(trigger.lower() in lowered for trigger in triggers):
            facets.append(facet)
    has_enumeration = bool(_LIST_SEPARATORS_RE.search(original)) or bool(
        re.search(r"(?:分别|各自|几个方向|从.+?(?:方向|方面))", original, re.I)
    )
    if has_enumeration and not facets:
        # Chinese technical names commonly occur in an explicit list but are
        # not captured by the Latin-token entity regex.  Only take list items,
        # never arbitrary prose fragments.
        for group in re.findall(r"(?:从|包括|包含|涉及|就)?([^？?。；;]{2,80})(?:分别|各自|几个方向|方向|方面|[？?])", original):
            for part in _LIST_SEPARATORS_RE.split(group):
                term = part.strip(" ：:()（）")
                if (
                    2 <= len(term) <= 32
                    and not re.search(r"^(请|说明|比较|什么|如何|哪些|给出|排查|控制|行为|应如何配置|判断)$", term)
                    and (
                        re.search(r"[A-Za-z][A-Za-z0-9_.+\-]*", term)
                        or re.search(r"配置|通信|可靠|分片|重传|资源|网络|端序|序列化|匹配|发现|状态|数据|类型|主题|截止|活性|心跳", term)
                    )
                ):
                    facets.append(term)
    return tuple(dict.fromkeys(facets))


def rewrite_query(question: str) -> QueryRewrite:
    original = (question or "").strip()
    lowered = original.lower().replace("\u3000", " ")
    terms: list[str] = []
    for triggers, expansions in _RULES:
        if any(trigger.lower() in lowered for trigger in triggers):
            for term in expansions:
                if term not in terms:
                    terms.append(term)
    for triggers, expansions in _TERM_ALIASES:
        if any(trigger.lower() in lowered for trigger in triggers):
            for term in expansions:
                if term not in terms:
                    terms.append(term)
    entities = tuple(dict.fromkeys(token.strip(".,:;!?()[]{}") for token in _TECHNICAL_ENTITY_RE.findall(original) if token.strip(".,:;!?()[]{}")))
    accepted_entities, rejected_entities = _entity_facet_classification(original, entities)
    known_core = ("Domain", "Domain ID", "Topic", "Type", "QoS", "Partition", "match")
    core = tuple(term for term in terms if term in known_core or term.lower() in lowered)
    scenarios = tuple(term for term in terms if term in {"收不到数据", "故障排查", "配置检测", "网络环境", "死锁", "监听器"})
    # Keep the full controlled DDS expansion.  Truncating here can discard the
    # semantic gloss that explains an API's state transition after preserving
    # its exact enum names.
    expansions = tuple(term for term in terms if term not in core and term not in scenarios and term not in entities)[:12]
    return QueryRewrite(
        original_query=original,
        core_terms=tuple(dict.fromkeys(core)),
        technical_entities=tuple(dict.fromkeys(entities + tuple(term for term in terms if term in known_core))),
        scenario_terms=tuple(dict.fromkeys(scenarios)),
        expansion_terms=tuple(dict.fromkeys(expansions)),
        required_facets=_explicit_required_facets(original, accepted_entities),
        relation_facets=tuple(dict(item) for item in _relation_facets(original, accepted_entities)),
        facet_diagnostics={
            "raw_extracted_facets": list(entities),
            "accepted_required_facets": list(_explicit_required_facets(original, accepted_entities)),
            "rejected_noise_facets": list(rejected_entities),
        },
    )
