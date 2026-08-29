"""Canonicalize MinerU visual records.

No IMAGE_SLOT matching is performed. MinerU content-list bbox is the visual
source of truth and is normalized to [0, 1]. Chunks are metadata only and are
never used to decide a visual's physical position.
"""
from __future__ import annotations

from typing import Any, Iterable
from .mineru_reader import MinerUImage


def _norm_bbox(box: list[float] | tuple[float, ...] | None) -> list[float] | None:
    if not box or len(box) != 4:
        return None
    try:
        values = [float(value) for value in box]
    except (TypeError, ValueError):
        return None
    # MinerU v2 uses 0..1; legacy content_list uses 0..1000.
    scale = 1.0 if max(abs(value) for value in values) <= 1.5 else 1000.0
    values = [max(0.0, min(1.0, value / scale)) for value in values]
    if values[2] <= values[0] or values[3] <= values[1]:
        return None
    return values


def _iou(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    la = (left[2] - left[0]) * (left[3] - left[1])
    ra = (right[2] - right[0]) * (right[3] - right[1])
    return inter / max(la + ra - inter, 1e-9)


def _chunk_meta(chunks: list[dict[str, Any]], page: int) -> tuple[str | None, str | None]:
    same_page = [chunk for chunk in chunks if int(chunk.get("page") or 0) == page]
    if not same_page:
        return None, None
    chunk = same_page[0]
    return chunk.get("chunk_id"), chunk.get("section")


def _dedupe_images(images: list[MinerUImage]) -> list[MinerUImage]:
    """Compatibility shim: preserve every MinerU source occurrence.

    Previous versions removed records by image path/hash/bbox overlap.  That is
    unsafe because a PDF may intentionally contain the same visual more than
    once, including overlapping occurrences on one page.  The canonical
    occurrence identity is the record itself (unique image_id/order), so this
    function only sorts and never deletes.
    """
    return sorted(images, key=lambda item: (item.page, item.order, item.image_id))


def match_images(chunks: Iterable[dict[str, Any]], images: Iterable[MinerUImage], reserved_slot_ids: set[str] | None = None) -> list[dict[str, Any]]:
    chunk_list = list(chunks)
    output: list[dict[str, Any]] = []
    for image in _dedupe_images(list(images)):
        chunk_id, section = _chunk_meta(chunk_list, image.page)
        bbox = _norm_bbox(image.bbox)
        output.append({
            "image_id": image.image_id,
            "source_occurrence_id": f"mineru:{image.page}:{image.order}:{image.image_id}",
            "path": image.image_path,
            "page": image.page,
            "bbox": bbox,
            "coordinate_space": "normalized_0_1",
            "mineru_type": str(image.raw_type or "").lower(),
            "caption": image.caption,
            "chunk_id": chunk_id,
            "section": section,
            "match_score": 100 if bbox else 0,
            "match_status": "auto_matched" if bbox else "review",
            "slot_id": None,
            "slot_status": "not_used",
        })
    return output


def match_code_records(chunks: Iterable[dict[str, Any]], records: Iterable[dict[str, Any]], reserved_slot_ids: set[str] | None = None) -> list[dict[str, Any]]:
    chunk_list = list(chunks)
    output: list[dict[str, Any]] = []
    for occurrence_index, record in enumerate(sorted(records, key=lambda item: (item.get("page", 0), item.get("order", 0), item.get("code_id", "")))):
        page = int(record.get("page") or 0)
        bbox = _norm_bbox(record.get("bbox"))
        chunk_id, section = _chunk_meta(chunk_list, page)
        code_id = str(record.get("code_id") or f"code-p{page}-{occurrence_index + 1:02d}")
        output.append({**record, "code_id": code_id, "source_occurrence_id": f"mineru-code:{page}:{record.get('order', occurrence_index)}:{code_id}", "page": page, "bbox": bbox, "coordinate_space": "normalized_0_1", "chunk_id": chunk_id, "section": section, "slot_id": None, "match_score": 100 if bbox else 0, "match_status": "auto_matched" if bbox else "review", "slot_status": "not_used"})
    return output


def match_visual_records(chunks: Iterable[dict[str, Any]], images: Iterable[MinerUImage], codes: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunk_list = list(chunks)
    return match_images(chunk_list, images), match_code_records(chunk_list, codes)


__all__ = ["match_code_records", "match_images", "match_visual_records"]
