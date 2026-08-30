"""Canonical visual-occurrence registry shared by Markdown and chunks output."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
from pathlib import PurePath
import re


def _box(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    scale = 1.0 if max(abs(item) for item in result) <= 1.5 else 1000.0
    result = [item / scale for item in result]
    return result if result[2] > result[0] and result[3] > result[1] else None


def _iou(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    la = (left[2] - left[0]) * (left[3] - left[1])
    ra = (right[2] - right[0]) * (right[3] - right[1])
    return inter / max(la + ra - inter, 1e-9)


def _missing_path(value: Any) -> bool:
    return value is None or not str(value).strip() or str(value).strip().replace("\\", "/").endswith("images/")


def _is_thin_table_fragment(match: dict[str, Any]) -> bool:
    bbox = _box(match.get("bbox"))
    if not bbox:
        return False
    return (bbox[3] - bbox[1]) / max(bbox[2] - bbox[0], 1e-9) < 0.07


@dataclass
class VisualOccurrence:
    occurrence_id: str
    source_kind: str
    page: int
    bbox: list[float] | None
    path: str | None
    caption: str | None
    visual_type: str
    roles: list[str]
    semantic_owner_chunk_id: str | None
    binding_status: str
    binding_reason: str | None
    resolution_status: str
    needs_review: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_visual_registry(matches: list[dict[str, Any]], codes: list[dict[str, Any]], enrichments: dict[str, dict[str, Any]], canonical_paths: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonicalize visual/code records by physical occurrence, not hash alone."""
    canonical = list(matches)
    remaining_codes: list[dict[str, Any]] = []
    registry: list[VisualOccurrence] = []
    for match in canonical:
        image_id = str(match.get("image_id") or "")
        enrichment = enrichments.setdefault(image_id, {})
        path = (canonical_paths or {}).get(image_id) or match.get("path") or None
        if _missing_path(path):
            path = None
        caption_value = str(match.get("caption") or enrichment.get("caption") or "")
        has_figure_caption = bool(re.match(r"^(?:图\s*\d+|Figure\s+\d+|Fig\.\s*\d+)\b", caption_value, re.IGNORECASE))
        is_structured_duplicate = (
            path is None
            and str(match.get("mineru_type") or "").lower() == "table"
            and match.get("slot_status") == "table_not_slot"
            and not has_figure_caption
        )
        match["path"] = path
        if is_structured_duplicate:
            match["visual_class"] = "structured_table_duplicate"
            match["record_status"] = "table_excluded"
            match["resolution_status"] = "ignored_non_knowledge"
            match["needs_review"] = False
            enrichment["image_type"] = "table_image"
        else:
            # A formal figure caption is stronger evidence of an independent
            # visual occurrence than a VLM/table label.  Keep such figures in
            # the unified projection instead of suppressing them as tables.
            if has_figure_caption and enrichment.get("image_type") == "table_image":
                enrichment["image_type"] = "operation_screenshot"
                if match.get("record_status") == "table_excluded":
                    match["record_status"] = "candidate"
            match.setdefault("resolution_status", "resolved" if path else "missing_source")
            match.setdefault("binding_status", "ambiguous" if not match.get("chunk_id") else "resolved")
            match.setdefault("needs_review", match.get("binding_status") != "resolved" or not path)
            match.setdefault("visual_class", "knowledge_visual")
        # A formal figure caption keeps an occurrence in the knowledge-visual
        # projection even when an earlier table heuristic left a stale status.
        visual_type = (
            "structured_table_duplicate"
            if not has_figure_caption and (is_structured_duplicate or match.get("record_status") in {"table_excluded", "table_header_excluded"})
            else str(enrichment.get("image_type") or "unknown")
        )
        registry.append(VisualOccurrence(image_id, "pdf_native" if str(match.get("source_image_policy", "")).startswith("embedded") else "mineru", int(match.get("page") or 0), _box(match.get("bbox")), path, match.get("caption") or enrichment.get("caption"), visual_type, [visual_type], match.get("chunk_id"), str(match.get("binding_status") or "ambiguous"), match.get("binding_reason"), str(match.get("resolution_status") or ("resolved" if path else "missing_source")), bool(match.get("needs_review"))))
    for code in codes:
        path = code.get("source_image_path") or None
        if path:
            duplicate = next((match for match in canonical if PurePath(str(match.get("path"))).name == PurePath(str(path)).name and int(match.get("page") or 0) == int(code.get("page") or 0) and _iou(_box(match.get("bbox")), _box(code.get("bbox"))) >= 0.85), None)
        else:
            duplicate = None
        if duplicate:
            image_id = str(duplicate.get("image_id") or "")
            enrichment = enrichments.setdefault(image_id, {})
            roles = list(enrichment.get("roles") or [])
            roles.extend([str(enrichment.get("image_type") or "unknown"), "code_original"])
            enrichment["roles"] = sorted(set(roles))
            if code.get("code_content"):
                enrichment["code_content"] = code.get("code_content")
            continue
        remaining_codes.append(code)
    # Refresh registry metadata after code-role merges.
    for item in registry:
        value = enrichments.get(item.occurrence_id, {})
        if item.visual_type != "structured_table_duplicate":
            item.visual_type = str(value.get("image_type") or item.visual_type)
        item.roles = sorted(set((value.get("roles") or item.roles)))
    serialized = []
    for item in registry:
        value = item.to_dict()
        value["visual_class"] = "structured_table_duplicate" if item.visual_type == "structured_table_duplicate" else "knowledge_visual"
        serialized.append(value)
    return canonical, remaining_codes, serialized


__all__ = ["VisualOccurrence", "build_visual_registry"]
