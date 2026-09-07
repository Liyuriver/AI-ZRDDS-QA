"""Candidate normalization, deduplication and reciprocal-rank fusion."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def content_hash(content: str) -> str:
    return hashlib.sha256(_text(content).encode("utf-8")).hexdigest()


def normalize_candidate(item: dict[str, Any], source: str, rank: int) -> dict[str, Any]:
    content = _text(item.get("content") or item.get("quote"))
    source_file = str(item.get("source_file") or item.get("document") or "")
    section = str(item.get("section") or item.get("segment_name") or "")
    chunk_id = str(item.get("chunk_id") or item.get("segment_id") or "")
    stable_id = chunk_id or f"{source_file}:{section}:{content_hash(content)}"
    return {
        "id": str(item.get("id") or stable_id),
        "chunk_id": chunk_id,
        "source_file": source_file,
        "section": section,
        "content": content,
        "raw_score": float(item.get("raw_score", item.get("score", 0)) or 0),
        "rank": rank,
        "retrieval_source": [source],
        "page": item.get("page") or item.get("page_start") or 0,
        "images": item.get("images") or [],
        "_dedup_key": stable_id,
    }


def _same_content(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = _text(left.get("content")), _text(right.get("content"))
    if not a or not b:
        return False
    if content_hash(a) == content_hash(b):
        return True
    # Avoid brittle prefix/truncation matching; this is a token-set similarity.
    ta, tb = set(re.findall(r"[\w\u4e00-\u9fff]+", a.lower())), set(re.findall(r"[\w\u4e00-\u9fff]+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / max(1, len(ta | tb)) >= 0.92


def fuse_candidates(
    bm25_results: Iterable[dict[str, Any]],
    dify_results: Iterable[dict[str, Any]],
    *,
    top_n: int = 15,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for source, results in (("bm25", bm25_results), ("dify", dify_results)):
        for rank, raw in enumerate(results, 1):
            candidate = normalize_candidate(raw, source, rank)
            match = next((item for item in merged if (
                (candidate["chunk_id"] and item["chunk_id"] == candidate["chunk_id"])
                or candidate["_dedup_key"] == item["_dedup_key"]
                or _same_content(candidate, item)
            )), None)
            contribution = 1.0 / (rrf_k + rank)
            if match is None:
                candidate["fusion_score"] = contribution
                merged.append(candidate)
            else:
                match["fusion_score"] += contribution
                for value in candidate["retrieval_source"]:
                    if value not in match["retrieval_source"]:
                        match["retrieval_source"].append(value)
                if not match.get("chunk_id") and candidate.get("chunk_id"):
                    match["chunk_id"] = candidate["chunk_id"]
    merged.sort(key=lambda item: (-item["fusion_score"], item.get("_dedup_key", "")))
    for item in merged[:top_n]:
        item.pop("_dedup_key", None)
    return merged[:top_n]
