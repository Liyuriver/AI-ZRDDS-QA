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
    (("重复读取", "read以后", "read 以后", "同一批数据", "return_loan", "samplestate"),
     ("read", "take", "take_next_sample", "SampleState", "return_loan")),
    (("内容过滤", "过滤主题", "content filter"),
     ("ContentFilteredTopic", "filter_expression", "parameter")),
    (("idl", "结构体", "生成文件", "只替换", "新增成员"),
     ("IDL", "生成文件", "zrddsgen", "类型一致", "类型不一致", "序列化", "反序列化")),
    (("listener", "监听器", "data_available", "回调", "死锁"),
     ("DataReader", "Listener", "DATA_AVAILABLE", "on_data_available", "回调限制", "死锁")),
)


def rewrite_query(question: str) -> QueryRewrite:
    original = (question or "").strip()
    lowered = original.lower().replace("\u3000", " ")
    terms: list[str] = []
    for triggers, expansions in _RULES:
        if any(trigger.lower() in lowered for trigger in triggers):
            for term in expansions:
                if term not in terms:
                    terms.append(term)
    entities = tuple(dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]*", original)))
    known_core = ("Domain", "Domain ID", "Topic", "Type", "QoS", "Partition", "match")
    core = tuple(term for term in terms if term in known_core or term.lower() in lowered)
    scenarios = tuple(term for term in terms if term in {"收不到数据", "故障排查", "配置检测", "网络环境", "死锁", "监听器"})
    expansions = tuple(term for term in terms if term not in core and term not in scenarios and term not in entities)[:6]
    return QueryRewrite(
        original_query=original,
        core_terms=tuple(dict.fromkeys(core)),
        technical_entities=tuple(dict.fromkeys(entities + tuple(term for term in terms if term in known_core))),
        scenario_terms=tuple(dict.fromkeys(scenarios)),
        expansion_terms=tuple(dict.fromkeys(expansions)),
    )
