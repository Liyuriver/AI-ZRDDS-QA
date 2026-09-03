"""Deterministic confidence calculation from retrieval evidence only."""

from collections.abc import Mapping, Sequence
from numbers import Real

from app.config import CONFIDENCE_HIGH_THRESHOLD, CONFIDENCE_LOW_THRESHOLD


def normalize_evidence(raw_results) -> list[dict]:
    """Convert Dify/source/retrieval shapes into one evidence shape."""
    if isinstance(raw_results, Mapping):
        raw_results = raw_results.get("evidence", raw_results.get("sources", raw_results.get("retrieval_results", [])))
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        return []
    normalized = []
    for raw in raw_results:
        if isinstance(raw, Mapping):
            item = dict(raw)
            # Dify retriever_resources calls the excerpt quote/content depending on deployment.
            if not item.get("content") and item.get("quote"):
                item["content"] = item["quote"]
            normalized.append(item)
    return normalized


def _score(item: Mapping) -> float | None:
    value = item.get("rerank_score", item.get("retrieval_score", item.get("score", item.get("raw_score"))))
    return float(value) if isinstance(value, Real) and not isinstance(value, bool) else None


def normalize_score(value: float | None, scores: Sequence[float] = ()) -> float | None:
    if value is None:
        return None
    # Dify deployments commonly expose either [0, 1] or percentage/point scores.
    # Do not use sigmoid: its mapping would invent confidence.
    if 0 <= value <= 1:
        return value
    if scores:
        low, high = min(scores), max(scores)
        if high > low:
            return max(0.0, min(1.0, (value - low) / (high - low)))
    return max(0.0, min(1.0, value / 100.0)) if 0 <= value <= 100 else None


def confidence_level(score: float) -> str:
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return "HIGH"
    if score >= CONFIDENCE_LOW_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def calculate_confidence(evidence: Sequence[Mapping], version_status: str = "UNKNOWN",
                         requested_version: str | None = None) -> dict:
    normalized_evidence = normalize_evidence(evidence)
    valid = [item for item in normalized_evidence if item.get("content")]
    raw_scores = [s for item in valid if (s := _score(item)) is not None]
    normalized = sorted((normalize_score(s, raw_scores) for s in raw_scores if normalize_score(s, raw_scores) is not None), reverse=True)
    reasons: list[str] = []
    if not valid:
        return {"confidence_score": 0.0, "confidence_level": "LOW", "confidence_reasons": ["no_evidence"]}
    if not normalized:
        reasons.append("missing_retrieval_score")
        score = 0.20
    else:
        top1 = normalized[0]
        margin = top1 - normalized[1] if len(normalized) > 1 else 0.0
        score = 0.65 * top1 + 0.10 * min(1.0, margin * 2) + 0.15 * min(1.0, len(valid) / 2)
        if top1 >= 0.75:
            reasons.append("strong_top1")
        if margin >= 0.15:
            reasons.append("clear_margin")
        if len(valid) >= 2:
            reasons.append("multiple_supporting_evidence")
    versions = {str(item.get("version")).strip().lower() for item in valid if item.get("version")}
    if version_status == "MATCHED":
        score += 0.10
        reasons.append("version_matched")
    elif version_status in {"MIXED", "MISMATCH"}:
        score *= 0.45
        reasons.append("version_conflict")
    else:
        reasons.append("version_unknown")
    score = max(0.0, min(1.0, score))
    return {"confidence_score": round(score, 4), "confidence_level": confidence_level(score),
            "confidence_reasons": reasons}
