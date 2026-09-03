"""Unified question orchestration without changing retrieval/preprocessing."""

import logging
import re
from collections.abc import Mapping, Sequence

from app.services.metadata.version_service import extract_version, normalize_version
from app.services.qa.answer_decision_service import decide_answer
from app.services.qa.confidence_service import calculate_confidence

logger = logging.getLogger(__name__)


def normalize_question(query: str) -> str:
    value = re.sub(r"\s+", " ", str(query or "")).strip()
    return value.translate(str.maketrans({"，": ",", "。": ".", "：": ":", "？": "?"}))


def is_version_sensitive(query: str, evidence: Sequence[Mapping] = ()) -> bool:
    if len({str(x.get("version")).lower() for x in evidence if x.get("version")}) > 1:
        return True
    text = query.lower()
    return bool(re.search(r"\b(api|sdk|dll|lib|header)\b", text) or
                re.search(r"配置|安装|参数|版本|环境|错误码|链接|缺失|找不到", text))


def _evidence_versions(evidence: Sequence[Mapping]) -> set[str]:
    return {normalize_version(str(item.get("version"))) for item in evidence if item.get("version")}


def determine_version_status(evidence: Sequence[Mapping], requested_version: str | None,
                             sensitive: bool) -> str:
    versions = _evidence_versions(evidence)
    requested = normalize_version(requested_version)
    if not versions:
        return "UNKNOWN"
    if len(versions) > 1:
        return "MIXED"
    if requested is None:
        return "UNKNOWN"
    return "MATCHED" if requested in versions else "MISMATCH"


async def answer_question(original_query: str, *, version: str | None = None,
                          conversation_id: str | None = None, user_id: str | None = None,
                          ai_client=None) -> dict:
    from app.services.ai_client import AIClient
    client = ai_client or AIClient()
    original = str(original_query)
    detected = extract_version(original)
    requested = normalize_version(version)
    effective = requested or (normalize_version(detected) if detected else None)
    rag_query = normalize_question(original)
    if effective and not re.search(r"\bv?\s*" + re.escape(effective) + r"\b", rag_query, re.IGNORECASE):
        rag_query = f"ZRDDS V{effective} {rag_query}".strip()
    response = await client.query(rag_query, version=effective, conversation_id=conversation_id, user_id=user_id)
    evidence = response.get("evidence", response.get("sources", [])) or []
    sensitive = is_version_sensitive(original, evidence)
    vstatus = determine_version_status(evidence, effective, sensitive)
    confidence = calculate_confidence(evidence, vstatus, effective)
    answer_status, refusal = decide_answer(evidence, confidence["confidence_level"], vstatus, sensitive, effective)
    answer = refusal or response.get("answer", "")
    logger.info("QA query=%r rag_query=%r version_source=%s version_status=%s evidence_count=%d top1_score=%s top2_score=%s margin=%s confidence_score=%s confidence_level=%s answer_status=%s",
                original, rag_query, "explicit" if requested else ("query" if detected else "unknown"), vstatus,
                len(evidence), evidence[0].get("raw_score") if evidence else None,
                evidence[1].get("raw_score") if len(evidence) > 1 else None, None,
                confidence["confidence_score"], confidence["confidence_level"], answer_status)
    return {**response, "status": "answered" if answer_status == "ANSWER" else "insufficient_evidence",
            "answer": answer, "original_query": original, "rag_query": rag_query,
            "requested_version": ("V" + requested if requested else None),
            "detected_version": detected, "effective_version": ("V" + effective if effective else None),
            "version_source": "explicit" if requested else ("query" if detected else "unknown"),
            "version_status": vstatus, "evidence": evidence, "answer_status": answer_status, **confidence}
