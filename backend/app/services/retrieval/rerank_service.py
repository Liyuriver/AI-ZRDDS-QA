"""Alibaba Cloud DashScope reranking with a safe RRF fallback."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_WORKSPACE_ID,
    RERANK_ENABLED,
    RERANK_MODEL,
    RERANK_TOP_N,
)

logger = logging.getLogger(__name__)


def _search_terms(value: Any) -> set[str]:
    """Build language-agnostic lexical features for the offline reranker."""
    text = re.sub(r"\s+", "", str(value or "").lower())
    ascii_terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    chinese_terms = {chinese[index:index + 2] for index in range(len(chinese) - 1)}
    return ascii_terms | chinese_terms


def _coverage(query_terms: set[str], value: Any) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & _search_terms(value)) / len(query_terms)


def _fallback(query: str, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    """Use local lexical relevance when the external semantic reranker is unavailable."""
    # Minimal callers that do not provide section metadata cannot be scored
    # reliably beyond the fused order.  Preserve the RRF order for that
    # compatibility path; indexed knowledge chunks carry sections and use the
    # lexical fallback below.
    if not any(item.get("section") for item in candidates):
        ranked = sorted(
            candidates,
            key=lambda item: (-float(item.get("fusion_score", 0)), item.get("id", "")),
        )[:top_n]
        for rank, item in enumerate(ranked, 1):
            item["rerank_score"] = float(item.get("fusion_score", 0))
            item["rerank_rank"] = rank
        return ranked
    query_terms = _search_terms(query)
    max_fusion = max((float(item.get("fusion_score", 0)) for item in candidates), default=1.0)

    for item in candidates:
        section = item.get("section") or ""
        content = item.get("content") or ""
        lexical_score = (
            0.72 * _coverage(query_terms, f"{section} {content}")
            + 0.18 * _coverage(query_terms, section)
        )
        rrf_score = float(item.get("fusion_score", 0)) / max_fusion if max_fusion else 0.0
        item["local_rerank_score"] = lexical_score + 0.10 * rrf_score

    ranked = sorted(
        candidates,
        key=lambda item: (
            -float(item.get("local_rerank_score", 0)),
            -float(item.get("fusion_score", 0)),
            item.get("id", ""),
        ),
    )[:top_n]
    for rank, item in enumerate(ranked, 1):
        item["rerank_score"] = float(item.get("local_rerank_score", 0))
        item["rerank_rank"] = rank
    return ranked


def _parse_results(payload: Any, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    output = payload.get("output") if isinstance(payload, dict) else None
    results = output.get("results") if isinstance(output, dict) else None
    if not isinstance(results, list):
        raise ValueError("DashScope response has no output.results list")

    ranked: list[dict[str, Any]] = []
    for rank, result in enumerate(results, 1):
        if not isinstance(result, dict):
            raise ValueError("DashScope result is not an object")
        index = result.get("index")
        score = result.get("relevance_score")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(candidates):
            raise ValueError("DashScope returned an invalid index")
        if isinstance(score, bool):
            raise ValueError("DashScope returned an invalid relevance_score")
        try:
            score = float(score)
        except (TypeError, ValueError) as exc:
            raise ValueError("DashScope returned an invalid relevance_score") from exc
        item = candidates[index]
        item["rerank_score"] = score
        item["rerank_rank"] = rank
        ranked.append(item)
    if not ranked:
        raise ValueError("DashScope returned no results")
    return ranked[:top_n]


def rerank(query: str, candidates: list[dict[str, Any]], top_n: int = RERANK_TOP_N) -> list[dict[str, Any]]:
    """Return a ranked candidate pool; final evidence sizing happens later."""
    if not candidates:
        return []

    workspace_id = (DASHSCOPE_WORKSPACE_ID or "").strip()
    api_key = (DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY") or "").strip().strip("\"'")
    request_url = (
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/rerank/text-rerank/text-rerank"
        if workspace_id else "<missing-workspace-id>"
    )
    provider = "dashscope"

    if not RERANK_ENABLED:
        logger.warning(
            "rerank provider=%s model=%s request_url=%s http_status=disabled candidate_count=%s fallback=True",
            provider, RERANK_MODEL, request_url, len(candidates),
        )
        return _fallback(query, candidates, top_n)
    if not api_key or not workspace_id:
        logger.warning(
            "rerank provider=%s model=%s request_url=%s http_status=not_configured candidate_count=%s fallback=True",
            provider, RERANK_MODEL, request_url, len(candidates),
        )
        return _fallback(query, candidates, top_n)

    payload = {
        "model": RERANK_MODEL,
        "input": {
            "query": query,
            "documents": [str(item.get("content") or "") for item in candidates],
        },
        "parameters": {"top_n": min(top_n, len(candidates))},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            response = client.post(request_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
        logger.info(
            "rerank provider=%s model=%s request_url=%s http_status=%s candidate_count=%s fallback=False",
            provider, RERANK_MODEL, request_url, response.status_code, len(candidates),
        )
        return _parse_results(result, candidates, top_n)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "rerank provider=%s model=%s request_url=%s http_status=%s candidate_count=%s fallback=True",
            provider, RERANK_MODEL, request_url, status or type(exc).__name__, len(candidates),
        )
        return _fallback(query, candidates, top_n)
