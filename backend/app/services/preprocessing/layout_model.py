"""Canonical document layout model and deterministic Markdown rendering.

The final Markdown is generated once from parsed source blocks plus MinerU
visual/code blocks. No IMAGE_SLOT replacement or post-render insertion exists.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class PageBlock:
    block_id: str
    page: int
    bbox: tuple[float, float, float, float] | None
    order: int
    kind: str
    text: str = ""
    heading_level: int | None = None
    heading_path: str | None = None
    source: str = "pdfplumber"
    confidence: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def _to_page_bbox(parsed: Any, page: int, value: Any) -> tuple[float, float, float, float] | None:
    box = _bbox(value)
    if not box:
        return None
    width, height = getattr(parsed, "page_sizes", {}).get(page, (1.0, 1.0))
    # Visual records are canonicalized to 0..1 by image_context_matcher.
    if max(abs(item) for item in box) <= 1.5:
        return (box[0] * width, box[1] * height, box[2] * width, box[3] * height)
    return box


def _iou(left: tuple[float, float, float, float] | None, right: tuple[float, float, float, float] | None) -> float:
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


def _centre_inside(inner: tuple[float, float, float, float] | None, outer: tuple[float, float, float, float] | None) -> bool:
    if not inner or not outer:
        return False
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _horizontal_overlap_ratio(left: tuple[float, float, float, float] | None, right: tuple[float, float, float, float] | None) -> float:
    if not left or not right:
        return 0.0
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    denom = max(min(left[2] - left[0], right[2] - right[0]), 1e-9)
    return overlap / denom


def mark_table_header_visuals(parsed: Any, matches: Iterable[dict[str, Any]], enrichments: dict[str, dict[str, Any]]) -> set[str]:
    """Mark visual fragments that are actually a table header/title.

    The rule is document-agnostic: a candidate must geometrically belong to the
    top of a reliable pdfplumber table on the same page. Explicit VLM figure,
    screenshot, flow or code classifications always win and are never removed.
    """
    tables_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for block in getattr(parsed, "blocks", []):
        if getattr(block, "kind", "") != "table":
            continue
        box = _bbox(getattr(block, "bbox", None))
        if box:
            tables_by_page.setdefault(int(getattr(block, "page", 0)), []).append(box)

    excluded: set[str] = set()
    protected_types = {"operation_screenshot", "configuration_screenshot", "code_or_config", "terminal_or_log", "architecture_or_flow"}
    for match in matches:
        image_id = str(match.get("image_id") or "")
        if not image_id:
            continue
        enrichment = enrichments.get(image_id, {})
        image_type = str(enrichment.get("image_type") or "unknown")
        if image_type in protected_types:
            continue
        page = int(match.get("page") or 0)
        visual = _to_page_bbox(parsed, page, match.get("bbox"))
        if not visual:
            continue
        width, height = getattr(parsed, "page_sizes", {}).get(page, (1.0, 1.0))
        vh = visual[3] - visual[1]
        vw = visual[2] - visual[0]
        raw_type = str(match.get("mineru_type") or "").lower()
        caption = str(match.get("caption") or enrichment.get("caption") or "").strip()

        for table in tables_by_page.get(page, []):
            th = table[3] - table[1]
            tw = table[2] - table[0]
            if th <= 0 or tw <= 0:
                continue
            x_overlap = _horizontal_overlap_ratio(visual, table)
            if x_overlap < 0.82:
                continue
            top_margin = max(12.0, height * 0.018)
            top_band = table[1] + min(th * 0.38, height * 0.08)
            centre_y = (visual[1] + visual[3]) / 2
            inside_top = table[1] - top_margin <= centre_y <= top_band and visual[3] <= table[1] + th * 0.48
            gap = table[1] - visual[3]
            directly_above = -top_margin <= gap <= top_margin and vw >= tw * 0.55
            small_header = vh <= max(th * (0.55 if raw_type == "table" else 0.32), height * 0.065)
            caption_like = bool(caption and caption.lstrip().startswith(("表", "Table", "TABLE")))
            table_fragment = raw_type == "table" and (_iou(visual, table) >= 0.08 or _centre_inside(visual, table))

            if (small_header and (inside_top or directly_above)) or (caption_like and directly_above) or table_fragment:
                match["record_status"] = "table_header_excluded"
                match["table_header_for"] = [round(value, 3) for value in table]
                excluded.add(image_id)
                break
    return excluded


def bind_source_figure_captions(parsed: Any, matches: Iterable[dict[str, Any]], enrichments: dict[str, dict[str, Any]]) -> None:
    """Bind each visual to the nearest explicit source caption (图 N ...) once."""
    captions_by_page: dict[int, list[tuple[tuple[float, float, float, float], str]]] = {}
    for block in getattr(parsed, "blocks", []):
        text = str(getattr(block, "text", "")).strip()
        box = _bbox(getattr(block, "bbox", None))
        if not box or not re.match(r"^图\s*\d+\s*\S", text):
            continue
        captions_by_page.setdefault(int(getattr(block, "page", 0)), []).append((box, text))

    used: set[tuple[int, str]] = set()
    visual_items: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    for match in matches:
        page = int(match.get("page") or 0)
        box = _to_page_bbox(parsed, page, match.get("bbox"))
        if box:
            visual_items.append((match, box))
    visual_items.sort(key=lambda item: (int(item[0].get("page") or 0), item[1][1], item[1][0]))

    for match, visual in visual_items:
        page = int(match.get("page") or 0)
        candidates: list[tuple[float, str]] = []
        page_height = getattr(parsed, "page_sizes", {}).get(page, (1.0, 1.0))[1]
        max_gap = max(40.0, page_height * 0.09)
        for caption_box, text in captions_by_page.get(page, []):
            key = (page, text)
            if key in used:
                continue
            below_gap = caption_box[1] - visual[3]
            above_gap = visual[1] - caption_box[3]
            # Captions normally sit directly below a visual; allow a smaller
            # above-image fallback for unusual manuals.
            if -8.0 <= below_gap <= max_gap:
                distance = max(0.0, below_gap)
            elif 0.0 <= above_gap <= max_gap * 0.55:
                distance = above_gap + max_gap * 0.25
            else:
                continue
            x_overlap = _horizontal_overlap_ratio(visual, caption_box)
            centre_dx = abs(((visual[0] + visual[2]) / 2) - ((caption_box[0] + caption_box[2]) / 2))
            score = distance - x_overlap * 18.0 + centre_dx * 0.03
            candidates.append((score, text))
        if not candidates:
            continue
        _, caption = min(candidates, key=lambda item: item[0])
        used.add((page, caption))
        image_id = str(match.get("image_id") or "")
        if image_id:
            enrichment = enrichments.setdefault(image_id, {})
            enrichment["caption"] = caption
            enrichment["caption_source"] = "pdf_source_nearest_caption"


def _visual_markdown(match: dict[str, Any], enrichment: dict[str, Any], image_path: str | None) -> str:
    if not image_path:
        return f"<!-- UNRESOLVED_VISUAL image_id={match.get('image_id', '')} page={match.get('page', '')} reason=missing_source -->"
    caption = enrichment.get("caption") or match.get("caption") or match.get("image_id", "image")
    lines = [f"![{caption}]({image_path})"]
    image_type = str(enrichment.get("image_type") or "unknown")
    code = str(enrichment.get("code_content") or "").strip()

    # User-facing policy: source/config code screenshots are best represented by
    # the exact text itself. Do not add a redundant narrative image summary.
    if image_type == "code_or_config" and code:
        image_box = "\n".join(f"> {line}" if line else ">" for line in lines)
        return image_box + "\n\n```text\n" + code + "\n```"

    description = str(enrichment.get("description") or "").strip()
    key_information = [str(value).strip() for value in (enrichment.get("key_information") or []) if str(value).strip()]
    if description or key_information:
        lines.extend(["", "**图示信息：**"])
        if description:
            lines.append(f"- {description}")
        for value in key_information:
            if value != description:
                lines.append(f"- {value}")

    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _canonical_visuals(parsed: Any, matches: Iterable[dict[str, Any]], enrichments: dict[str, dict[str, Any]], image_paths: dict[str, str]) -> list[PageBlock]:
    result: list[PageBlock] = []
    for index, match in enumerate(matches):
        image_id = match.get("image_id")
        if not image_id:
            continue
        if match.get("record_status") == "table_header_excluded":
            continue
        page = int(match.get("page") or 0)
        box = _to_page_bbox(parsed, page, match.get("bbox"))
        enrichment = enrichments.get(image_id, {})
        # Only an explicit VLM table classification suppresses an image. A raw
        # MinerU/table label alone is not enough because screenshots are often
        # geometrically table-like.
        if enrichment.get("image_type") == "table_image":
            kind = "table_visual"
            text = ""
        else:
            kind = "image"
            text = _visual_markdown(match, enrichment, image_paths.get(image_id))
        result.append(PageBlock(
            block_id=str(image_id),
            page=page,
            bbox=box,
            order=1_000_000 + index,
            kind=kind,
            text=text,
            heading_path=match.get("section"),
            source="mineru+vlm",
            confidence=float(match.get("match_score") or 0) / 100.0,
            metadata={"image_id": image_id, "mineru_type": match.get("mineru_type"), "image_type": enrichment.get("image_type")},
        ))
    # Do not deduplicate by path/hash/bbox.  Repeated and even overlapping
    # visuals can be genuine source occurrences.  Each unique image_id is
    # rendered exactly once by this single rendering pipeline.
    return sorted(result, key=lambda item: (item.page, item.bbox[1] if item.bbox else 10**9, item.bbox[0] if item.bbox else 10**9, item.order))


def _canonical_codes(parsed: Any, codes: Iterable[dict[str, Any]]) -> list[PageBlock]:
    result: list[PageBlock] = []
    for index, code in enumerate(codes):
        if code.get("record_status") == "non_code_visual_excluded":
            continue
        content = str(code.get("code_content") or "").strip()
        source_image = str(code.get("source_image_path") or "").strip()
        if not content and not source_image:
            continue
        page = int(code.get("page") or 0)
        box = _to_page_bbox(parsed, page, code.get("bbox"))
        verification_status = str(code.get("code_verification_status") or "")

        if source_image:
            lines = ["> ![代码区域原图](" + source_image + ")"]
            if content:
                lines.extend([">", "> **解析代码：**", "", "```text", content, "```"])
                if verification_status == "primary_context_corrected":
                    lines.extend([">", "> **校验提示：** 已仅依据同页源文档中存在的技术字符串校正疑似 OCR 字符；未拼接其他识别结果，原图同时保留。"])
                elif verification_status == "primary_review":
                    lines.extend([">", "> **校验提示：** VLM 精确转写与 MinerU/PDF 证据存在差异，代码未被拼接或修正，请结合原图复核。"])
                elif verification_status == "primary_unverified":
                    lines.extend([">", "> **校验提示：** 当前代码来自单次 VLM 精确转写，缺少可靠的独立文本证据；原图同时保留。"])
            elif verification_status == "primary_rejected":
                lines.extend([">", "> **解析代码：未输出。VLM 精确转写与独立证据冲突且置信度不足，原图作为可信来源。**"])
            elif verification_status == "primary_transcription_empty":
                lines.extend([">", "> **解析代码：未输出。未获得可靠的代码文本，原图作为可信来源。**"])
            elif verification_status == "primary_transcription_failed":
                lines.extend([">", "> **解析代码：未输出。代码精确转写调用失败，原图已保留。**"])
            else:
                lines.extend([">", "> **解析代码：暂无可信文本结果，原图已保留。**"])
            text = "\n".join(lines)
            kind = "code_figure"
        else:
            text = "```text\n" + content + "\n```"
            kind = "code"

        result.append(PageBlock(
            block_id=str(code.get("code_id") or f"code-{page}-{index}"),
            page=page,
            bbox=box,
            order=2_000_000 + index,
            kind=kind,
            text=text,
            heading_path=code.get("section"),
            source="vlm+pdf_crop" if source_image else "vlm",
            confidence=float(code.get("match_score") or 0) / 100.0,
            metadata={
                "code_content": content,
                "source_image_path": source_image or None,
                "source_visual_id": code.get("source_visual_id"),
                "code_verification_status": verification_status or None,
                "code_content_candidate": code.get("code_content_candidate"),
                "code_transcription_confidence": code.get("code_transcription_confidence"),
                "mineru_code_content": code.get("mineru_code_content"),
                "code_context_corrections": code.get("code_context_corrections") or [],
            },
        ))
    return result

def _normalise_text(value: str) -> str:
    """Whitespace-insensitive comparison used only for duplicate suppression."""
    value = value.replace("```text", "").replace("```", "")
    value = value.replace("–", "-").replace("—", "-")
    return "".join(value.split()).lower()


def _dedupe_codes_against_source(parsed: Any, code_blocks: list[PageBlock], visual_blocks: list[PageBlock]) -> list[PageBlock]:
    """Keep physical code occurrences while avoiding parser duplicates.

    Same code text at different PDF positions is legitimate and must survive.
    A code crop is retained even when selectable text exists underneath. If an
    existing visual already owns the same region, reuse that original visual and
    emit only the parsed code text when it is not already present there.
    """
    page_text: dict[int, str] = {}
    for source in getattr(parsed, "blocks", []):
        if getattr(source, "heading_level", None):
            continue
        if getattr(source, "kind", "text") == "table":
            continue
        page = int(getattr(source, "page", 0))
        page_text.setdefault(page, "")
        page_text[page] += "\n" + str(getattr(source, "text", ""))

    kept: list[PageBlock] = []
    for block in code_blocks:
        metadata = block.metadata or {}
        content = str(metadata.get("code_content") or block.text.removeprefix("```text\n").removesuffix("\n```")).strip()
        norm = _normalise_text(content)
        if not norm:
            if metadata.get("source_image_path"):
                kept.append(block)
            continue
        owner = next((
            visual for visual in visual_blocks
            if visual.page == block.page and visual.kind == "image" and block.bbox and visual.bbox
            and (_centre_inside(block.bbox, visual.bbox) or _iou(block.bbox, visual.bbox) >= 0.45)
        ), None)
        if owner:
            # When the code record is linked to an original visual occurrence,
            # the code_figure owns that occurrence: keep original image + parsed
            # code together and suppress the separate visual later.
            if metadata.get("source_image_path"):
                kept.append(block)
                continue
            # Otherwise avoid emitting a second copy of code already described
            # by the visual/VLM block.
            if norm in _normalise_text(owner.text):
                continue
            kept.append(PageBlock(
                block_id=block.block_id,
                page=block.page,
                bbox=block.bbox,
                order=block.order,
                kind="code",
                text="```text\n" + content + "\n```",
                heading_path=block.heading_path,
                source="mineru",
                confidence=block.confidence,
                metadata={"code_content": content, "source_image_path": None, "source_visual_id": metadata.get("source_visual_id")},
            ))
            continue

        source_norm = _normalise_text(page_text.get(block.page, ""))
        has_original_crop = bool(metadata.get("source_image_path"))
        if not has_original_crop and len(norm) >= 6 and norm in source_norm:
            continue
        kept.append(block)
    return kept


def build_page_blocks(parsed: Any, matches: Iterable[dict[str, Any]], codes: Iterable[dict[str, Any]], enrichments: dict[str, dict[str, Any]], image_paths: dict[str, str]) -> list[PageBlock]:
    """Merge canonical source blocks with visual/code blocks in page order."""
    bind_source_figure_captions(parsed, matches, enrichments)
    visual_blocks = _canonical_visuals(parsed, matches, enrichments, image_paths)
    raw_code_blocks = _canonical_codes(parsed, codes)

    # A MinerU table record is suppressed only if a reliable pdfplumber table
    # overlaps the same region. Otherwise keep the visual so a misclassified
    # screenshot is not lost.
    parsed_tables = [block for block in getattr(parsed, "blocks", []) if getattr(block, "kind", "") == "table"]
    kept_visuals: list[PageBlock] = []
    for visual in visual_blocks:
        if visual.kind != "table_visual":
            kept_visuals.append(visual)
            continue
        overlap = any(table.page == visual.page and _iou(getattr(table, "bbox", None), visual.bbox) >= 0.45 for table in parsed_tables)
        if not overlap:
            # No trustworthy structured table covers it; keep the source visual
            # rather than silently deleting a possible figure/screenshot.
            match_id = visual.metadata.get("image_id") if visual.metadata else visual.block_id
            path = image_paths.get(str(match_id))
            if path:
                kept_visuals.append(PageBlock(visual.block_id, visual.page, visual.bbox, visual.order, "image", f"![{match_id}]({path})", visual.heading_level, visual.heading_path, visual.source, visual.confidence, visual.metadata))

    # Prefer original selectable PDF text over a duplicate MinerU code record.
    # This also prevents serialized payloads / repeated boxed notes from being
    # rendered a second time below the real source content.
    code_blocks = _dedupe_codes_against_source(parsed, raw_code_blocks, kept_visuals)

    # A code_figure may reuse one existing visual occurrence as its original
    # appearance. Render that source occurrence once, inside the code_figure,
    # instead of once as image and once as code_figure.
    code_owned_visual_ids = {
        str((block.metadata or {}).get("source_visual_id"))
        for block in code_blocks
        if block.kind == "code_figure" and (block.metadata or {}).get("source_visual_id")
    }
    if code_owned_visual_ids:
        kept_visuals = [
            block for block in kept_visuals
            if str((block.metadata or {}).get("image_id")) not in code_owned_visual_ids
        ]

    all_nontext_regions = [block for block in kept_visuals + code_blocks if block.bbox]
    blocks: list[PageBlock] = []
    heading_stack: dict[int, str] = {}

    for index, source in enumerate(getattr(parsed, "blocks", [])):
        page = int(getattr(source, "page", 0))
        box = _bbox(getattr(source, "bbox", None))
        kind = getattr(source, "kind", "text")
        level = getattr(source, "heading_level", None)
        text = str(getattr(source, "text", ""))

        if level:
            heading_stack = {k: v for k, v in heading_stack.items() if k < level}
            heading_stack[level] = text
        heading_path = " > ".join(heading_stack[key] for key in sorted(heading_stack)) or None

        # Selectable text layered inside screenshots/code regions must not leak
        # into normal正文. Headings are never suppressed. A pdfplumber table is
        # also suppressed when a non-table visual clearly owns the region.
        if not level and box:
            owner = next((region for region in all_nontext_regions if region.page == page and (_centre_inside(box, region.bbox) or _iou(box, region.bbox) >= 0.60)), None)
            if owner:
                if kind in {"text", "box", "code"}:
                    continue
                if kind == "table" and owner.kind == "image":
                    continue

        if level:
            rendered = f"{'#' * level} {text}"
            output_kind = "heading"
        elif kind in {"box", "code"}:
            rendered = "```text\n" + text.strip("\n") + "\n```"
            output_kind = kind
        else:
            rendered = text
            output_kind = kind
        blocks.append(PageBlock(
            block_id=f"src-{index:06d}",
            page=page,
            bbox=box,
            order=int(getattr(source, "order", index)),
            kind=output_kind,
            text=rendered,
            heading_level=level,
            heading_path=heading_path,
            source="pdfplumber",
            confidence=1.0,
        ))

    blocks.extend(kept_visuals)
    blocks.extend(code_blocks)

    def sort_key(block: PageBlock) -> tuple[float, float, float, int]:
        if block.bbox:
            return (float(block.page), float(block.bbox[1]), float(block.bbox[0]), block.order)
        # Positionless blocks stay after positioned source content on that page.
        return (float(block.page), 10**9, 10**9, block.order)

    return sorted(blocks, key=sort_key)


def render_page_blocks(document: str, blocks: Iterable[PageBlock]) -> str:
    """Render exactly once. Heading levels are preserved, never re-written."""
    lines = [f"# {document.removesuffix('.pdf')}", ""]
    for block in blocks:
        if not block.text:
            continue
        lines.extend([block.text, ""])
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["PageBlock", "bind_source_figure_captions", "build_page_blocks", "mark_table_header_visuals", "render_page_blocks"]
