"""Read already-generated MinerU content-list output.

MinerU is intentionally not invoked here.  The reader accepts the two common
content-list filenames and preserves the raw records for auditability.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MinerUImage:
    image_id: str
    image_path: str | None
    page: int
    bbox: list[float] | None
    raw_type: str | None
    caption: str | None
    nearby_before: list[str] = field(default_factory=list)
    nearby_after: list[str] = field(default_factory=list)
    raw_ocr_text: str | None = None
    order: int = 0
    previous_heading: str | None = None
    next_heading: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(record: dict[str, Any]) -> str:
    value = _first(record, "text", "ocr_text", "raw_text")
    if value is None:
        content = record.get("content", record)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, dict):
            value = content.get("text")
            if value is None:
                for key in ("title_content", "paragraph_content", "table_caption", "image_caption"):
                    if content.get(key):
                        value = content[key]
                        break
    if isinstance(value, dict):
        return _text(value)
    if isinstance(value, list):
        return " ".join(_text(item) if isinstance(item, dict) else str(item) for item in value if item).strip()
    return str(value).strip() if value is not None else ""


def _caption(record: dict[str, Any]) -> str | None:
    content = record.get("content") if isinstance(record.get("content"), dict) else record
    value = _first(content, "image_caption", "table_caption", "caption", "title")
    if isinstance(value, list):
        value = " ".join(str(item.get("content", item)) if isinstance(item, dict) else str(item) for item in value)
    return str(value).strip() if value else None


def _heading(record: dict[str, Any]) -> str | None:
    if str(record.get("type", "")).lower() not in {"title", "heading"}:
        return None
    content = record.get("content")
    if isinstance(content, dict):
        value = content.get("title_content") or content.get("text") or content.get("content")
    else:
        value = content
    if isinstance(value, list):
        value = " ".join(_text(item) if isinstance(item, dict) else str(item) for item in value)
    value = str(value).strip() if value else None
    return value if value and re.match(r"^\d+(?:\.\d+)*\.", value) else None


def _page(record: dict[str, Any]) -> int:
    value = _first(record, "page_idx", "page_id", "page")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"MinerU image record has no numeric page: {record!r}") from exc
    # page_idx is the documented zero-based field; page/page_id are treated as
    # already one-based for compatibility with exported content lists.
    return number + 1 if "page_idx" in record else number


def _bbox(record: dict[str, Any]) -> list[float] | None:
    """Return the source bbox unchanged; consumers normalize at their boundary."""
    value = _first(record, "bbox", "box", "coordinate")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _image_path(record: dict[str, Any]) -> str | None:
    value = _first(record, "img_path", "image_path", "path", "image")
    content = record.get("content")
    if value is None and isinstance(content, dict):
        source = content.get("image_source")
        if isinstance(source, dict):
            value = _first(source, "path", "img_path", "image_path")
    if isinstance(value, dict):
        value = _first(value, "path", "img_path", "image_path")
    return str(value) if value else None


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        # MinerU v2 exports one list per zero-based PDF page.
        if payload and all(isinstance(page, list) for page in payload):
            records = []
            for page_idx, page in enumerate(payload):
                for item in page:
                    if isinstance(item, dict):
                        record = dict(item)
                        record.setdefault("page_idx", page_idx)
                        records.append(record)
            return records
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("content_list", "data", "items", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"Unsupported MinerU content list shape: {path}")


def _bbox_iou(left: list[float] | None, right: list[float] | None) -> float:
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


def _dedupe_visuals(items: list[MinerUImage]) -> list[MinerUImage]:
    """Keep one canonical record for one physical visual region."""
    result: list[MinerUImage] = []
    for item in sorted(items, key=lambda value: (value.page, value.order, value.image_id)):
        # A repeated source file/path may be intentionally placed more than once
        # in the PDF.  Deduplicate occurrences only when they occupy the same
        # physical region on the same page.
        duplicate = next((i for i, old in enumerate(result) if old.page == item.page and _bbox_iou(old.bbox, item.bbox) >= 0.92), None)
        if duplicate is None:
            result.append(item)
            continue
        old = result[duplicate]
        old_type = str(old.raw_type or "").lower()
        new_type = str(item.raw_type or "").lower()
        if old_type == "table" and new_type in {"image", "figure", "chart"}:
            result[duplicate] = item
    return result


def read_mineru_output(output_dir: Path) -> list[MinerUImage]:
    """Read images from ``*_content_list_v2.json`` or its v1 fallback."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise FileNotFoundError(f"MinerU output directory not found: {output_dir}")
    candidates = sorted(output_dir.glob("*_content_list_v2.json"))
    if not candidates:
        candidates = sorted(output_dir.glob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"No *_content_list_v2.json or *_content_list.json in {output_dir}")
    if len(candidates) > 1:
        raise ValueError("Ambiguous MinerU content lists under %s: %s; select exactly one target list" % (output_dir, ", ".join(path.name for path in candidates)))

    records: list[dict[str, Any]] = []
    records = _load_records(candidates[0])

    result: list[MinerUImage] = []
    headings = [_heading(record) for record in records]
    for index, record in enumerate(records):
        image_path = _image_path(record)
        raw_type = _first(record, "type", "category", "class")
        if not image_path and str(raw_type or "").lower() not in {"image", "figure", "table"}:
            continue
        image_path = image_path or ""
        page = _page(record)
        record_page = _page(record)
        before = [_text(item) for item in records[max(0, index - 3):index] if _text(item)]
        after = [_text(item) for item in records[index + 1:index + 4] if _text(item)]
        requested_id = str(_first(record, "image_id", "id") or f"img-p{page}-{len(result) + 1:02d}")
        used_ids = {item.image_id for item in result}
        image_id = requested_id
        suffix = 2
        while image_id in used_ids:
            image_id = f"{requested_id}-{suffix}"
            suffix += 1
        result.append(MinerUImage(
            image_id=image_id,
            image_path=image_path,
            page=page,
            bbox=_bbox(record),
            raw_type=str(raw_type) if raw_type is not None else None,
            caption=_caption(record),
            nearby_before=before,
            nearby_after=after,
            raw_ocr_text=_text(record) or None,
            order=index,
            previous_heading=next((heading for heading in reversed(headings[:index]) if heading), None),
            next_heading=next((heading for heading in headings[index + 1:] if heading), None),
            raw={**record, "missing_mineru_source": not bool(image_path)},
        ))
    # Preserve every source occurrence exactly once.  Two records may point to
    # identical bytes and may even overlap on the same page because the source
    # PDF itself can contain repeated/overlapping occurrences.  Geometry/hash/
    # path are therefore matching evidence only and are never deletion rules.
    return result


def _code_text(value: Any) -> str:
    """Flatten MinerU code payloads without leaking Python list/dict repr."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("code_content", "code_body", "algorithm_content", "text", "content"):
            if key in value:
                text = _code_text(value.get(key))
                if text:
                    return text
        return ""
    if isinstance(value, list):
        parts = [_code_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


def _normalise_code(value: str) -> str:
    return "".join(value.replace("–", "-").replace("—", "-").split()).lower()


def read_mineru_code(output_dir: Path) -> list[dict[str, Any]]:
    """Read every MinerU code occurrence without text/hash deduplication.

    Prefer the v2 content list and fall back to v1 rather than reading both and
    then deleting duplicates by code text.  Identical code can legitimately
    occur more than once on the same page, so occurrence order/bbox is the only
    safe identity.
    """
    output_dir = Path(output_dir)
    candidates = sorted(output_dir.glob("*_content_list_v2.json"))
    if not candidates:
        candidates = sorted(output_dir.glob("*_content_list.json"))

    records: list[dict[str, Any]] = []
    if len(candidates) > 1:
        raise ValueError("Ambiguous MinerU content lists under %s: %s; select exactly one target list" % (output_dir, ", ".join(path.name for path in candidates)))
    records = _load_records(candidates[0])

    result: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        raw_type = str(_first(record, "type", "category", "class") or "").lower()
        content = record.get("content")
        body_value = _first(record, "code_body", "code_content", "code", "text")
        if body_value is None:
            body_value = content
        if raw_type not in {"code", "algorithm"} and not record.get("code_body") and not record.get("code_content"):
            continue
        body = _code_text(body_value).replace(r"\$", "$").replace(r"\_", "_").strip()
        if not body:
            continue
        page = _page(record)
        result.append({
            "code_id": f"code-p{page}-{len(result) + 1:02d}",
            "source_occurrence_id": f"mineru-code:p{page}:o{index + 1}",
            "page": page,
            "bbox": _bbox(record),
            "order": index,
            "code_content": body,
            "raw": record,
        })
    return result


__all__ = ["MinerUImage", "read_mineru_code", "read_mineru_output"]
