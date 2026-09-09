"""Controlled, deterministic expansion from user wording to DDS terminology."""

from dataclasses import dataclass
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
     ("IDL", "ZRDDS", "生成文件", "zrddsgen", "类型一致", "类型不一致", "序列化", "反序列化")),
    (("listener", "监听器", "data_available", "回调", "死锁"),
     ("DataReader", "Listener", "DATA_AVAILABLE", "on_data_available", "回调限制", "死锁")),
)


_TECHNICAL_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*")
_LIST_SEPARATORS_RE = re.compile(r"[、,/，；;]|\b(?:and|or|vs)\b|(?:与|和|及|以及|并且)", re.I)
_NON_FACET_ENTITIES = {"compare", "explain", "describe", "how", "does", "what", "which", "the", "and", "or", "with", "from", "for", "work", "works", "must", "on", "to", "by", "who", "why", "where", "when", "match", "matches", "offer", "offers", "offered", "provide", "provides", "provided", "produce", "produces", "request", "requests", "requested", "require", "requires", "consume", "consumes", "compatible", "compatibility"}


def _relation_facets(original: str, entities: tuple[str, ...]) -> tuple[dict, ...]:
    """Extract role/constraint relations without using product vocabularies.

    The extractor deliberately records roles and constraints, not a list of
    known DDS policies.  This lets the evidence layer match equivalent
    producer/consumer and offered/requested wording across languages.
    """
    text = original.lower()
    if not re.search(r"(?:offered|requested|provide|provides|produce|consume|require|depend|compatible|match|满足|提供|产生|请求|要求|依赖|兼容|匹配|不满足|规则|判断)", text, re.I):
        return ()
    clean_entities = [e for e in entities if e.lower() not in _NON_FACET_ENTITIES]
    subjects = [e for e in clean_entities if re.search(r"writer|reader|producer|consumer|publisher|subscriber", e, re.I)]
    for match in re.finditer(r"([A-Za-z][A-Za-z0-9_.+\-]*)\s+(?:offers?|provides?|produces?|requests?|requires?|consumes?|depends?)\b", original, re.I):
        if match.group(1) not in subjects:
            subjects.append(match.group(1))
    objects = [e for e in clean_entities if e not in subjects and e.lower() not in _NON_FACET_ENTITIES]
    obj = " ".join(objects) if objects else "the shared capability"
    relations: list[dict] = []
    offer_words = bool(re.search(r"offered|offer|provide|provides|produce|发布|提供|产生|生产", text, re.I))
    request_words = bool(re.search(r"requested|request|require|consume|订阅|请求|要求|消费|依赖", text, re.I))
    if subjects and offer_words:
        relations.append({"subject": subjects[0], "relation": "offers", "object": obj, "constraint_type": "role", "required": True})
    if len(subjects) > 1 and request_words:
        relations.append({"subject": subjects[1], "relation": "requests", "object": obj, "constraint_type": "role", "required": True})
    if (offer_words and request_words) or re.search(r"兼容|匹配|不满足|compatible|match|satisf", text, re.I):
        relations.append({"subject": subjects[0] if subjects else "producer", "relation": "matches", "object": obj, "constraint_type": "compatibility_rule", "required": True})
    return tuple(dict.fromkeys((tuple(sorted(item.items())) for item in relations)))


def _explicit_required_facets(original: str, entities: tuple[str, ...]) -> tuple[str, ...]:
    """Keep user-requested technical directions separate from retrieval hints.

    This intentionally uses syntax and exact entities rather than a DDS term
    list, so new vocabularies and mixed-language questions follow the same
    path.  A single explicit entity is also a required facet; that keeps the
    representation uniform for single-facet questions.
    """
    facets: list[str] = [entity for entity in entities if entity.lower() not in _NON_FACET_ENTITIES]
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
                if 2 <= len(term) <= 32 and not re.search(r"^(请|说明|比较|什么|如何|哪些|给出|排查|控制|行为)$", term):
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
    entities = tuple(dict.fromkeys(token.strip(".,:;!?()[]{}") for token in _TECHNICAL_ENTITY_RE.findall(original) if token.strip(".,:;!?()[]{}")))
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
        required_facets=_explicit_required_facets(original, entities),
        relation_facets=tuple(dict(item) for item in _relation_facets(original, entities)),
    )
