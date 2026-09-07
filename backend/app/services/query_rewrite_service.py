"""Controlled, deterministic expansion from user wording to DDS terminology."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryRewrite:
    original: str
    terms: tuple[str, ...]

    @property
    def search_query(self) -> str:
        return " ".join((self.original, *self.terms))


_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("阻塞等待", "多个dds状态", "多个 DDS 状态"),
     ("WaitSet", "Condition", "StatusCondition", "wait", "同步等待")),
    (("topic一样", "topic名字一样", "topic 名字一样", "收不到数据", "无法通信", "不匹配"),
     ("收不到数据", "故障排查", "配置检测", "Domain", "Domain ID", "Topic", "Type", "QoS", "Partition", "match", "匹配")),
    (("重复读取", "read以后", "read 以后", "同一批数据", "return_loan", "samplestate"),
     ("read", "take", "take_next_sample", "SampleState", "return_loan")),
    (("内容过滤", "过滤主题", "content filter"),
     ("ContentFilteredTopic", "filter_expression", "parameter")),
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
    # Keep the expansion deliberately bounded even if more rules are added later.
    return QueryRewrite(original=original, terms=tuple(terms[:10]))
