"""Candidate normalization, deduplication and reciprocal-rank fusion.

Source-balanced candidate union:
  BM25 Top-N reserved + Dify Top-N reserved + RRF high-score supplements
  → dedup → rerank pool

This ensures high-ranking candidates from either retrieval source keep a fair
chance to reach rerank, instead of being crowded out by dual-source hits that
score higher under plain RRF.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

# Per-source high-rank reserve for the source-balanced candidate union.
# Used only for candidate_reason labeling when top_n is None; when top_n is
# set, this many slots are guaranteed per source before RRF supplements.
DEFAULT_RESERVE_N = 3


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _document_key(value: Any) -> str:
    return re.sub(r"\.pdf$", "", _text(value).lower())


def _section_key(value: Any) -> str:
    return re.sub(r"\s*[>#/]\s*", ">", _text(value).lower())


def content_hash(content: str) -> str:
    return hashlib.sha256(_text(content).encode("utf-8")).hexdigest()


def normalize_candidate(item: dict[str, Any], source: str, rank: int) -> dict[str, Any]:
    content = _text(item.get("content") or item.get("quote"))
    source_file = str(item.get("source_file") or item.get("document") or "")
    section = str(item.get("section") or item.get("segment_name") or "")
    chunk_id = str(item.get("chunk_id") or item.get("segment_id") or "")
    segment_id = item.get("segment_id") or item.get("segmentId")
    stable_id = f"{_document_key(source_file)}:{_section_key(section)}:{content_hash(content)}"
    return {
        "id": str(item.get("id") or stable_id),
        "chunk_id": chunk_id,
        "segment_id": str(segment_id) if segment_id is not None else None,
        "source_file": source_file,
        "section": section,
        "content": content,
        "raw_score": float(item.get("raw_score", item.get("score", 0)) or 0),
        "rank": rank,
        "retrieval_source": [source],
        "page": item.get("page") or item.get("page_start") or 0,
        "images": item.get("images") or [],
        "_dedup_key": stable_id,
        # per-source rank tracking (filled/merged during dedup)
        "bm25_rank": rank if source == "bm25" else None,
        "dify_rank": rank if source == "dify" else None,
    }


def _same_content(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = _text(left.get("content")), _text(right.get("content"))
    if not a or not b:
        return False
    left_doc, right_doc = _document_key(left.get("source_file")), _document_key(right.get("source_file"))
    left_section, right_section = _section_key(left.get("section")), _section_key(right.get("section"))
    # An exact normalized fingerprint is safe to merge even when one path
    # reports a different document label; this is common for exported Dify
    # segments.  Approximate matches remain protected by document/section.
    if content_hash(a) == content_hash(b):
        return True
    if left_doc and right_doc and left_doc != right_doc:
        return False
    if left_section and right_section and left_section != right_section:
        return False
    # Avoid brittle prefix/truncation matching; this is a token-set similarity.
    ta, tb = set(re.findall(r"[\w\u4e00-\u9fff]+", a.lower())), set(re.findall(r"[\w\u4e00-\u9fff]+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / max(1, len(ta | tb)) >= 0.92


def _merge_source_info(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge per-source rank and identity from *incoming* into *target*."""
    for value in incoming.get("retrieval_source", []):
        if value not in target["retrieval_source"]:
            target["retrieval_source"].append(value)
    if incoming.get("bm25_rank") is not None and target.get("bm25_rank") is None:
        target["bm25_rank"] = incoming["bm25_rank"]
    if incoming.get("dify_rank") is not None and target.get("dify_rank") is None:
        target["dify_rank"] = incoming["dify_rank"]
    if not target.get("chunk_id") and incoming.get("chunk_id"):
        target["chunk_id"] = incoming["chunk_id"]
    if not target.get("segment_id") and incoming.get("segment_id"):
        target["segment_id"] = incoming["segment_id"]


def _classify_candidate(item: dict[str, Any], reserve_n: int) -> str:
    """Assign candidate_reason: multi_source / bm25_reserved / dify_reserved / rrf_selected."""
    sources = item.get("retrieval_source", [])
    has_bm25 = "bm25" in sources
    has_dify = "dify" in sources
    if has_bm25 and has_dify:
        return "multi_source"
    if has_bm25 and item.get("bm25_rank") is not None and item["bm25_rank"] <= reserve_n:
        return "bm25_reserved"
    if has_dify and item.get("dify_rank") is not None and item["dify_rank"] <= reserve_n:
        return "dify_reserved"
    return "rrf_selected"


def _source_balanced_select(
    merged: list[dict[str, Any]], top_n: int, reserve_n: int
) -> list[dict[str, Any]]:
    """Build a source-balanced pool of at most *top_n* candidates.

    Priority: multi_source → BM25 reserved → Dify reserved → RRF supplements.
    Candidates are deduplicated across groups by their stable id.
    """
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(item: dict[str, Any]) -> bool:
        key = item.get("_dedup_key") or item.get("id") or ""
        if key in seen:
            return False
        seen.add(key)
        pool.append(item)
        return True

    # 1. multi-source candidates (hit by both BM25 and Dify → high confidence)
    for item in merged:
        if item["candidate_reason"] == "multi_source":
            _add(item)

    # 2. BM25 reserved: top reserve_n by BM25 per-source rank
    bm25_reserved = sorted(
        (i for i in merged if i["candidate_reason"] == "bm25_reserved"),
        key=lambda i: i.get("bm25_rank") or 999,
    )
    for item in bm25_reserved[:reserve_n]:
        _add(item)

    # 3. Dify reserved: top reserve_n by Dify per-source rank
    dify_reserved = sorted(
        (i for i in merged if i["candidate_reason"] == "dify_reserved"),
        key=lambda i: i.get("dify_rank") or 999,
    )
    for item in dify_reserved[:reserve_n]:
        _add(item)

    # 4. RRF high-score supplements (merged is already sorted by -fusion_score)
    if len(pool) < top_n:
        for item in merged:
            if len(pool) >= top_n:
                break
            _add(item)

    return pool[:top_n]


def fuse_candidates(
    bm25_results: Iterable[dict[str, Any]],
    dify_results: Iterable[dict[str, Any]],
    *,
    top_n: int | None = 15,
    rrf_k: int = 60,
    reserve_n: int | None = None,
) -> list[dict[str, Any]]:
    """Fuse BM25 and Dify candidates with source-balanced candidate union.

    Parameters
    ----------
    top_n:
        Maximum candidates to return.  ``None`` means no truncation (all
        deduplicated candidates pass through, still labeled with
        ``candidate_reason``).
    rrf_k:
        Reciprocal-rank fusion constant.
    reserve_n:
        Per-source high-rank reserve.  When ``None``: ``max(1, top_n // 3)``
        if *top_n* is set, otherwise :data:`DEFAULT_RESERVE_N`.

    Each returned candidate carries:
      ``source_hits``   – list of sources that recalled it (``["bm25","dify"]``)
      ``bm25_rank``     – BM25 per-source rank or ``None``
      ``dify_rank``     – Dify per-source rank or ``None``
      ``rrf_score``     – RRF fusion score (same as ``fusion_score``)
      ``candidate_reason`` – ``multi_source`` / ``bm25_reserved`` /
                         ``dify_reserved`` / ``rrf_selected``
    """
    # ---- Step 1: normalize + dedup + accumulate RRF ----
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
                _merge_source_info(match, candidate)

    # ---- Step 2: sort by RRF score ----
    merged.sort(key=lambda item: (-item["fusion_score"], item.get("_dedup_key", "")))

    # ---- Step 3: determine per-source reserve ----
    if reserve_n is None:
        reserve_n = max(1, top_n // 3) if top_n is not None else DEFAULT_RESERVE_N

    # ---- Step 4: label every candidate with trace fields ----
    for item in merged:
        item["source_hits"] = list(item.get("retrieval_source", []))
        item["rrf_score"] = item["fusion_score"]
        item["candidate_reason"] = _classify_candidate(item, reserve_n)

    # ---- Step 5: source-balanced truncation (only when top_n is set) ----
    if top_n is not None and len(merged) > top_n:
        result = _source_balanced_select(merged, top_n, reserve_n)
    else:
        result = merged

    # ---- Step 6: clean internal dedup key ----
    for item in result:
        item.pop("_dedup_key", None)

    return result
