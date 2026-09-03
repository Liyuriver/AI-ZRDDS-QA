"""Final backend answer gate."""

REFUSAL_LOW = "当前知识库中未检索到足够可靠的依据，暂时无法给出确定回答。请补充 ZRDDS 版本、错误日志或具体开发环境后重试。"
REFUSAL_VERSION = "当前检索到的资料存在版本适用性不确定，暂时无法确认该结论是否完全适用于你的环境。请补充具体 ZRDDS 版本后再继续。"


def decide_answer(evidence: list[dict], confidence_level: str, version_status: str,
                  version_sensitive: bool, requested_version: str | None) -> tuple[str, str | None]:
    if not evidence:
        return "NO_ANSWER", REFUSAL_LOW
    if confidence_level == "LOW":
        return "LOW_CONFIDENCE", REFUSAL_LOW
    if version_sensitive and (version_status in {"MIXED", "MISMATCH"} or
                              (requested_version is None and version_status == "MIXED")):
        return "VERSION_UNCERTAIN", REFUSAL_VERSION
    return "ANSWER", None
