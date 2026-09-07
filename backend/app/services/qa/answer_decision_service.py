"""Final backend answer gate."""

REFUSAL_LOW = "当前知识库中未检索到足够可靠的依据，暂时无法给出确定回答。请补充 ZRDDS 版本、错误日志或具体开发环境后重试。"
REFUSAL_VERSION = "当前检索到的资料存在版本适用性不确定，暂时无法确认该结论是否完全适用于你的环境。请补充具体 ZRDDS 版本后再继续。"


def _version_label(value: str | None) -> str:
    text = str(value or "").strip()
    return text if not text or text.lower().startswith("v") else f"V{text}"


def _mismatch_message(evidence: list[dict], requested_version: str | None) -> str:
    versions = {str(item.get("version")).strip() for item in evidence if item.get("version")}
    evidence_version = next(iter(versions), "")
    return (f"当前检索到的资料版本为 {_version_label(evidence_version)}，"
            f"与请求的 {_version_label(requested_version)} 不一致，"
            "无法确认该内容适用于你指定的版本。")


def decide_answer(evidence: list[dict], confidence_level: str, version_status: str,
                  version_sensitive: bool, requested_version: str | None) -> tuple[str, str | None]:
    if not evidence:
        return "NO_ANSWER", REFUSAL_LOW
    if version_status == "MISMATCH":
        return "VERSION_MISMATCH", _mismatch_message(evidence, requested_version)
    if version_status == "MIXED":
        return "VERSION_UNCERTAIN", REFUSAL_VERSION
    if confidence_level == "LOW":
        return "LOW_CONFIDENCE", REFUSAL_LOW
    return "ANSWER", None
