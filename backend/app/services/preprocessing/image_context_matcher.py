"""Canonicalize MinerU visual records.

No IMAGE_SLOT matching is performed. MinerU content-list bbox is the visual
source of truth and is normalized to [0, 1]. Chunks are metadata only and are
never used to decide a visual's physical position.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from app.services.preprocessing.mineru_reader import MinerUImage


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


def resolve_visual_chunk(visual: dict[str, Any] | MinerUImage, chunks: Iterable[dict[str, Any]], blocks: Iterable[Any] | None = None, page_sizes: dict[int, tuple[float, float]] | None = None) -> dict[str, Any]:
    """Resolve one visual using reading order and heading boundaries.

    A visual at the top of a page can belong to the section that continued
    from the previous page.  Page ranges remain candidates, but never decide
    ownership before the page's heading boundary has been considered.
    """
    chunk_list = list(chunks)
    page = int(visual.get("page") if isinstance(visual, dict) else visual.page)
    bbox = visual.get("bbox") if isinstance(visual, dict) else visual.bbox
    caption = str((visual.get("caption") if isinstance(visual, dict) else visual.caption) or "").strip()
    same_page = [chunk for chunk in chunk_list if page in (chunk.get("source_pages") or [chunk.get("page")])]
    if not same_page:
        return {"chunk_id": None, "section": None, "binding_status": "ambiguous", "binding_reason": "no_source_page_candidate", "binding_score": 0.0}
    if caption:
        normalized = re.sub(r"\s+", "", caption).lower()
        hits = [chunk for chunk in same_page if normalized in re.sub(r"\s+", "", str(chunk.get("content") or "")).lower()]
        if len(hits) == 1:
            return {"chunk_id": hits[0].get("chunk_id"), "section": hits[0].get("section"), "binding_status": "resolved", "binding_reason": "caption_match", "binding_score": 1.0}
    if bbox and blocks:
        width, height = (page_sizes or {}).get(page, (1.0, 1.0))
        y = ((float(bbox[1]) + float(bbox[3])) / 2) * height if max(abs(float(v)) for v in bbox) <= 1.5 else (float(bbox[1]) + float(bbox[3])) / 2
        nearby = [block for block in blocks if int(getattr(block, "page", 0) or 0) == page and getattr(block, "bbox", None)]
        if nearby:
            page_headings = sorted(
                (block for block in nearby if getattr(block, "heading_level", None)),
                key=lambda block: (block.bbox[1], block.order),
            )
            first_heading = page_headings[0] if page_headings else None
            # Before the first heading on a page, inherit the most recent
            # source-block interval that ended before that heading.  This is
            # the generic page-break case: previous section -> visual -> new
            # heading.  Once the heading has been passed, normal local order
            # resolution below selects the new section.
            if first_heading is not None and y < first_heading.bbox[1]:
                heading_order = int(getattr(first_heading, "order", 0))
                inherited = [
                    chunk for chunk in chunk_list
                    if chunk.get("source_block_end") is not None
                    and int(chunk.get("source_block_end")) < heading_order
                    and any(int(source_page or 0) < page for source_page in (chunk.get("source_pages") or [chunk.get("page")]))
                ]
                if inherited:
                    owner = max(inherited, key=lambda chunk: int(chunk.get("source_block_end") or -1))
                    return {"chunk_id": owner.get("chunk_id"), "section": owner.get("section"), "binding_status": "resolved", "binding_reason": "page_top_heading_inheritance", "binding_score": 0.92}
            preceding = [block for block in nearby if block.bbox[1] <= y]
            nearest = max(preceding, key=lambda block: (block.bbox[3], block.order)) if preceding else min(nearby, key=lambda block: abs(block.bbox[1] - y))
            owner = next((chunk for chunk in same_page if nearest.order in (chunk.get("source_block_ids") or [])), None)
            if owner:
                return {"chunk_id": owner.get("chunk_id"), "section": owner.get("section"), "binding_status": "resolved", "binding_reason": "source_block_interval", "binding_score": 0.9}
            text = str(getattr(nearest, "text", "") or "").strip()
            hits = [chunk for chunk in same_page if text and text in str(chunk.get("content") or "")]
            if len(hits) == 1:
                return {"chunk_id": hits[0].get("chunk_id"), "section": hits[0].get("section"), "binding_status": "resolved", "binding_reason": "source_block_proximity", "binding_score": 0.85}
    if len(same_page) == 1:
        chunk = same_page[0]
        return {"chunk_id": chunk.get("chunk_id"), "section": chunk.get("section"), "binding_status": "resolved", "binding_reason": "unique_source_page", "binding_score": 0.7}
    return {"chunk_id": None, "section": None, "binding_status": "ambiguous", "binding_reason": "multiple_source_page_candidates", "binding_score": 0.0}


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
        slot_id = None
        if bbox and str(image.raw_type or "").lower() != "table":
            for chunk in chunk_list:
                if int(chunk.get("page") or 0) != image.page:
                    continue
                for slot in re.finditer(r"<!-- IMAGE_SLOT id=(\S+) page=(\d+) bbox=([\d.,-]+) order=(\d+) -->", str(chunk.get("content") or "")):
                    slot_box = _norm_bbox([float(value) for value in slot.group(3).split(",")])
                    if slot_box and _iou(bbox, slot_box) >= 0.45:
                        slot_id = slot.group(1)
                        break
                if slot_id:
                    break
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
            "slot_id": slot_id,
            "slot_status": "table_not_slot" if str(image.raw_type or "").lower() == "table" else ("matched" if slot_id else "not_used"),
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


__all__ = ["match_code_records", "match_images", "match_visual_records", "resolve_visual_chunk"]
