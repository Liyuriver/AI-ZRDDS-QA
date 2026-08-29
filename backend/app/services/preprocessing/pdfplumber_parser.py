"""Reliable pdfplumber text extraction and structural chunking.

pdfplumber is used for source text and conservative table/boxed-code recovery.
Visual placement is not inferred here; MinerU supplies semantic visual regions.
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import median
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

# Numbered manual headings: 1, 1., 1.2, 1.2.3., with normal spacing.
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[\.．、])?\s+(.+?)\s*$")
CHAPTER_RE = re.compile(r"^第\s*([一二三四五六七八九十百零〇\d]+)\s*章\s*(.+?)\s*$")
APPENDIX_RE = re.compile(r"^附录\s*([一二三四五六七八九十百零〇\d]+)\s*[：:、.．]?\s*(.+?)\s*$")
PAGE_NUMBER_RE = re.compile(r"^(?:第\s*)?\d+(?:\s*页)?$")
ROMAN_PAGE_RE = re.compile(r"^[IVXLCDM]{1,8}$", re.IGNORECASE)
TOC_TITLE_RE = re.compile(r"^(?:目录|目\s*录|表格目录|图目录)$")
TOC_ENTRY_RE = re.compile(r"^(?:\d+(?:\.\d+)*|表格?\s*\d+|图\s*\d+|附录\s*\d+).{0,180}?\.{3,}\s*\d+\s*$")
BULLET_RE = re.compile(r"^[●•▪◼◆◇]\s*")
COMMAND_RE = re.compile(r"^zrddsgen(?:\.exe)?\s+[-–]", re.IGNORECASE)
KEY_VALUE_RE = re.compile(r"^(?:CPU|内存|磁盘空间|网络)[：:]")
END_PUNCTUATION = tuple("。；：！？.!?;:）)]}\"")
TABLE_PREFIX = "\0TABLE\0"


@dataclass
class Block:
    text: str
    page: int
    heading_level: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    order: int = 0
    kind: str = "text"  # text | heading | table | box | code | toc


@dataclass(frozen=True)
class ParsedDocument:
    document: str
    blocks: list[Block]
    chunks: list[dict]
    markdown: str
    page_sizes: dict[int, tuple[float, float]] = field(default_factory=dict)
    source_path: str | None = None
    source_image_occurrences: list[dict[str, Any]] = field(default_factory=list)


def normalize_line(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\u200b", "")
    line = BULLET_RE.sub("- ", line.strip())
    line = re.sub(r"[ \t]+", " ", line)
    line = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", line)
    return line.strip()




def _line_typography(raw: dict[str, Any]) -> tuple[float | None, float]:
    """Return median font size and bold-font fraction for one extracted line."""
    chars = raw.get("chars") or []
    sizes: list[float] = []
    bold = 0
    counted = 0
    for char in chars:
        try:
            size = float(char.get("size"))
        except (TypeError, ValueError):
            size = 0.0
        if size > 0:
            sizes.append(size)
        font = str(char.get("fontname") or "").lower()
        if font:
            counted += 1
            if "bold" in font or "black" in font or "semibold" in font:
                bold += 1
    return (median(sizes) if sizes else None, (bold / counted if counted else 0.0))


def _detect_toc_pages(line_items_by_page: dict[int, list[dict[str, Any]]], total_pages: int) -> set[int]:
    """Identify front-matter TOC/list-of-figures pages without document-specific names."""
    toc_pages: set[int] = set()
    front_limit = max(10, int(total_pages * 0.20))
    for page_number, items in line_items_by_page.items():
        if page_number > front_limit:
            continue
        texts = [str(item.get("text") or "").strip() for item in items if str(item.get("text") or "").strip()]
        if not texts:
            continue
        explicit = any(TOC_TITLE_RE.fullmatch(text) for text in texts[:8])
        leader_count = sum(bool(TOC_ENTRY_RE.match(text)) for text in texts)
        dotted_count = sum((text.count(".") >= 5 and bool(re.search(r"\d\s*$", text))) for text in texts)
        if explicit or leader_count >= 3 or dotted_count >= 5:
            toc_pages.add(page_number)
    # Continuation pages often omit the word 目录 but keep the same leader pattern.
    for page_number in range(2, front_limit + 1):
        if page_number in toc_pages or page_number - 1 not in toc_pages:
            continue
        texts = [str(item.get("text") or "").strip() for item in line_items_by_page.get(page_number, [])]
        leader_count = sum(bool(TOC_ENTRY_RE.match(text)) for text in texts)
        dotted_count = sum((text.count(".") >= 5 and bool(re.search(r"\d\s*$", text))) for text in texts)
        if leader_count >= 2 or dotted_count >= 3:
            toc_pages.add(page_number)
    return toc_pages


def _layout_heading_info(text: str, *, font_size: float | None, body_size: float | None, bold_fraction: float = 0.0, in_toc: bool = False) -> tuple[int, str] | None:
    """Accept numbered headings only when lexical and typography evidence agree."""
    if in_toc:
        return None
    candidate = _heading_info(text)
    if not candidate:
        return None
    if font_size is None or body_size is None or body_size <= 0:
        # Geometry-less compatibility inputs keep the legacy behaviour. Real PDF
        # extraction nearly always supplies typography and therefore uses the
        # stricter branch below.
        return candidate
    delta = font_size - body_size
    # Manual headings in native PDFs are normally larger than body text. A bold
    # same-size line is accepted only with a small positive size signal; this
    # prevents numbered instructions/log values from becoming headings.
    if delta >= 0.75:
        return candidate
    if delta >= 0.20 and bold_fraction >= 0.55:
        return candidate
    return None


def _protect_angle_tokens(text: str) -> str:
    """Protect placeholder/XML-like angle tokens from Markdown HTML stripping."""
    if not text or "<" not in text:
        return text
    pattern = re.compile(r"(?<!`)<(?!/?br\s*/?>)(?![!])[^<>\n]{1,160}>(?!`)", re.IGNORECASE)
    return pattern.sub(lambda m: f"`{m.group(0)}`", text)


def _logical_table_segments(rows: list[list[str | None]]) -> list[tuple[int, int]]:
    """Infer stable logical columns from PDF merged-cell structure.

    pdfplumber can expose tiny text-padding cells in one row while the same
    physical table uses merged cells in the other rows.  We choose the most
    frequently observed cell-start pattern; on a tie the more detailed pattern
    wins.  This is geometry/structure driven and contains no document-specific
    column count or header text rule.
    """
    if not rows:
        return []
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return []

    from collections import Counter
    patterns: Counter[tuple[int, ...]] = Counter()
    for row in rows:
        padded = list(row) + [None] * (width - len(row))
        starts = tuple(index for index, cell in enumerate(padded) if cell is not None)
        if starts:
            patterns[starts] += 1

    if not patterns:
        return [(index, index + 1) for index in range(width)]
    starts = max(patterns, key=lambda pattern: (patterns[pattern], len(pattern)))
    # For compact native tables, a sparsely populated grouping column (e.g.
    # server / ping-pong / throughput) may be omitted from the most frequent
    # rowspan pattern even though it is semantically real. Re-introduce an
    # omitted column only when it contains meaningful text in multiple rows.
    if width <= 6:
        meaningful_counts = []
        for index in range(width):
            count = 0
            for row in rows:
                cell = row[index] if index < len(row) else None
                if cell is not None and normalize_line(str(cell)):
                    count += 1
            meaningful_counts.append(count)
        augmented = set(starts)
        for index, count in enumerate(meaningful_counts):
            if index not in augmented and count >= 2:
                augmented.add(index)
        starts = tuple(sorted(augmented))

    segments: list[tuple[int, int]] = []
    for index, left in enumerate(starts):
        right = starts[index + 1] if index + 1 < len(starts) else width
        if right > left:
            segments.append((left, right))
    return segments or [(index, index + 1) for index in range(width)]


def compact_table_rows(rows: list[list[str | None]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    segments = _logical_table_segments(rows)
    compacted: list[list[str]] = []
    for row in rows:
        padded = list(row) + [None] * (width - len(row))
        cells: list[str] = []
        for left, right in segments:
            pieces = [normalize_line(cell or "").replace("\n", "<br>") for cell in padded[left:right] if cell is not None]
            pieces = [piece for piece in pieces if piece]
            # Several atomic cells inside one stable logical column are text
            # fragments, not extra columns. Preserve them in reading order.
            cells.append("<br>".join(pieces))
        if any(cells):
            compacted.append(cells)
    return compacted


def _logical_rows_to_markdown(rows: list[list[str]]) -> str | None:
    if not rows:
        return None
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return None
    normalized = [list(row) + [""] * (width - len(row)) for row in rows]
    if len(normalized) > 1:
        headers, body = normalized[0], normalized[1:]
    else:
        headers, body = [f"列 {i + 1}" for i in range(width)], normalized

    def render_row(row: list[str]) -> str:
        escaped = [_protect_angle_tokens(cell).replace("|", "\\|").replace("\n", "<br>") for cell in row]
        return "| " + " | ".join(escaped) + " |"

    return "\n".join([render_row(headers), render_row(["---"] * width), *(render_row(row) for row in body)])


def _table_raw_x_starts(table: Any, raw_width: int) -> list[float | None]:
    starts: list[list[float]] = [[] for _ in range(raw_width)]
    for row in getattr(table, "rows", []) or []:
        cells = getattr(row, "cells", []) or []
        for index in range(min(raw_width, len(cells))):
            cell = cells[index]
            if cell is not None:
                try:
                    starts[index].append(float(cell[0]))
                except (TypeError, ValueError, IndexError):
                    pass
    result: list[float | None] = []
    for values in starts:
        result.append(median(values) if values else None)
    return result


def _logical_x_starts(table: Any, rows: list[list[str | None]], segments: list[tuple[int, int]]) -> list[float]:
    raw_width = max((len(row) for row in rows), default=0)
    raw_starts = _table_raw_x_starts(table, raw_width)
    left_edge = float(table.bbox[0])
    right_edge = float(table.bbox[2])
    fallback_step = (right_edge - left_edge) / max(raw_width, 1)
    result: list[float] = []
    for left, _right in segments:
        value = raw_starts[left] if left < len(raw_starts) else None
        result.append(float(value) if value is not None else left_edge + left * fallback_step)
    return result


def _normalise_raw_rows(rows: list[list[str | None]], width: int) -> list[list[str]]:
    result: list[list[str]] = []
    for row in rows:
        padded = list(row) + [None] * (width - len(row))
        cells = [normalize_line(cell or "").replace("\n", "<br>") if cell is not None else "" for cell in padded[:width]]
        if any(cells):
            result.append(cells)
    return result


def _project_logical_rows(rows: list[list[str]], source_x: list[float], target_x: list[float]) -> list[list[str]]:
    if not rows or not target_x:
        return []
    if len(source_x) != max((len(row) for row in rows), default=0):
        return [list(row) for row in rows]
    projected: list[list[str]] = []
    for row in rows:
        out = [""] * len(target_x)
        for index, cell in enumerate(row):
            if not cell:
                continue
            sx = source_x[index]
            target_index = min(range(len(target_x)), key=lambda j: abs(target_x[j] - sx))
            out[target_index] = cell if not out[target_index] else out[target_index] + "<br>" + cell
        if any(out):
            projected.append(out)
    return projected


def table_to_markdown(rows: list[list[str | None]], headers_by_width: dict[int, list[str]] | None = None, carry_by_width: dict[int, list[str]] | None = None) -> str | None:
    """Render a table without document-specific column/header heuristics."""
    compacted = compact_table_rows(rows)
    if not compacted:
        return None
    return _logical_rows_to_markdown(compacted)


def _bbox_from_line(line: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        return (float(line["x0"]), float(line["top"]), float(line["x1"]), float(line["bottom"]))
    except (KeyError, TypeError, ValueError):
        chars = line.get("chars") or []
        if not chars:
            return None
        try:
            return (
                min(float(char["x0"]) for char in chars),
                min(float(char["top"]) for char in chars),
                max(float(char["x1"]) for char in chars),
                max(float(char["bottom"]) for char in chars),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _inside(box: tuple[float, float, float, float] | None, region: tuple[float, float, float, float]) -> bool:
    if not box:
        return False
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    la = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    ra = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    return inter / max(la + ra - inter, 1e-9)


def _table_is_reliable(rows: list[list[str | None]]) -> bool:
    compacted = compact_table_rows(rows)
    if len(compacted) < 2:
        return False
    width = max((len(row) for row in compacted), default=0)
    if width < 2:
        return False
    useful_rows = sum(sum(bool(cell.strip()) for cell in row) >= 2 for row in compacted)
    useful_cells = sum(bool(cell.strip()) for row in compacted for cell in row)
    return useful_rows >= 2 and useful_cells >= 4


def _heading_info(text: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(text)
    if match:
        number, title = match.groups()
        # H1 is reserved for the document title. 1 -> H2, 1.1 -> H3, ...
        level = min(number.count(".") + 2, 6)
        return level, f"{number} {title}".strip()
    match = CHAPTER_RE.match(text)
    if match:
        return 2, text
    match = APPENDIX_RE.match(text)
    if match:
        number, title = match.groups()
        return 2, f"附录 {number} {title}".strip()
    return None


def _looks_code_like(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    tokens = ("CONFIG", "TARGET", "TEMPLATE", "SOURCES", "HEADERS", "INCLUDEPATH", "LIBS", "DEFINES", "#include", "::", "=", "{", "}", "$(", "$$")
    score = sum(any(token in line for token in tokens) for line in lines)
    return score >= max(1, len(lines) // 2)


def _x_overlap_ratio(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    denom = max(min(left[2] - left[0], right[2] - right[0]), 1e-9)
    return overlap / denom


def _same_table_shape(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _x_overlap_ratio(left["bbox"], right["bbox"]) < 0.80:
        return False
    left_raw = int(left.get("raw_width") or 0)
    right_raw = int(right.get("raw_width") or 0)
    if left_raw >= 2 and left_raw == right_raw:
        return True
    left_rows = left.get("compacted") or []
    right_rows = right.get("compacted") or []
    if not left_rows or not right_rows:
        return False
    left_width = max(len(row) for row in left_rows)
    right_width = max(len(row) for row in right_rows)
    if left_width == right_width and left_width >= 2:
        return True
    # A continuation page can collapse several columns into merged cells. Allow
    # a narrower top-of-page fragment only when its physical starts align with
    # a subset of the wider table's logical columns.
    wide, narrow = (left, right) if left_width >= right_width else (right, left)
    wide_x = list(wide.get("logical_x_starts") or [])
    narrow_x = list(narrow.get("logical_x_starts") or [])
    if min(left_width, right_width) < 2 or not wide_x or not narrow_x:
        return False
    table_width = max(float(wide["bbox"][2] - wide["bbox"][0]), 1.0)
    return all(min(abs(nx - wx) for wx in wide_x) <= table_width * 0.20 for nx in narrow_x)


def _extract_blocks_from_pdf(pdf_path: Path) -> tuple[list[Block], dict[int, tuple[float, float]], list[dict[str, Any]]]:
    """Extract canonical source blocks plus a lossless PDF image-occurrence inventory.

    Tables are discovered for the whole document before rendering.  This lets a
    one-row header at the bottom of page N be joined to the body at the top of
    page N+1 without any document-specific header text or fixed column count.
    """
    blocks: list[Block] = []
    page_sizes: dict[int, tuple[float, float]] = {}
    source_image_occurrences: list[dict[str, Any]] = []

    with pdfplumber.open(pdf_path) as pdf:
        line_items_by_page: dict[int, list[dict[str, Any]]] = {}
        image_regions_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        table_candidates: list[dict[str, Any]] = []

        # First pass: build page geometry once.  page.images is used only as a
        # source-occurrence inventory / table veto; it never classifies content.
        for page_number, page in enumerate(pdf.pages, start=1):
            width, height = float(page.width), float(page.height)
            page_sizes[page_number] = (width, height)

            raw_lines = page.extract_text_lines(x_tolerance=2, y_tolerance=3) or []
            line_items: list[dict[str, Any]] = []
            for raw in raw_lines:
                text = normalize_line(str(raw.get("text", "")))
                if not text:
                    continue
                font_size, bold_fraction = _line_typography(raw)
                line_items.append({
                    "text": text,
                    "bbox": _bbox_from_line(raw),
                    "top": float(raw.get("top", 0.0)),
                    "font_size": font_size,
                    "bold_fraction": bold_fraction,
                })
            line_items_by_page[page_number] = line_items

            image_regions: list[tuple[float, float, float, float]] = []
            for occurrence_index, image in enumerate(page.images, start=1):
                try:
                    region = (float(image["x0"]), float(image["top"]), float(image["x1"]), float(image["bottom"]))
                except (KeyError, TypeError, ValueError):
                    continue
                image_regions.append(region)
                stream = image.get("stream")
                xref = getattr(stream, "objid", None)
                name = str(image.get("name") or "")
                source_image_occurrences.append({
                    "source_occurrence_id": f"pdf-image:p{page_number}:o{occurrence_index}:xref{xref or name or 'na'}",
                    "page": page_number,
                    "occurrence_index": occurrence_index,
                    "xref": xref,
                    "name": name or None,
                    "bbox": [region[0] / width, region[1] / height, region[2] / width, region[3] / height],
                    "coordinate_space": "normalized_0_1",
                    "srcsize": list(image.get("srcsize")) if isinstance(image.get("srcsize"), (list, tuple)) else None,
                })
            image_regions_by_page[page_number] = image_regions

            try:
                tables = sorted(page.find_tables(), key=lambda item: item.bbox[1])
            except Exception:
                tables = []
            for candidate_index, table in enumerate(tables):
                try:
                    region = tuple(float(value) for value in table.bbox)
                    rows = table.extract() or []
                except Exception:
                    continue
                # Embedded screenshots/code snippets often have rectangular
                # borders.  A real image XObject overlapping the candidate is a
                # hard veto against destructive table extraction.
                if any(_iou(region, image_region) >= 0.35 for image_region in image_regions):
                    continue
                segments = _logical_table_segments(rows)
                compacted = compact_table_rows(rows)
                if not compacted:
                    continue
                raw_width = max((len(row) for row in rows), default=0)
                table_candidates.append({
                    "id": f"table-p{page_number}-{candidate_index}",
                    "page": page_number,
                    "bbox": region,
                    "rows": rows,
                    "raw_width": raw_width,
                    "segments": segments,
                    "logical_x_starts": _logical_x_starts(table, rows, segments),
                    "compacted": compacted,
                    "reliable": _table_is_reliable(rows),
                })

        toc_pages = _detect_toc_pages(line_items_by_page, len(pdf.pages))
        body_size_by_page: dict[int, float | None] = {}
        for page_number, items in line_items_by_page.items():
            sizes = [float(item["font_size"]) for item in items if item.get("font_size") and not PAGE_NUMBER_RE.fullmatch(str(item.get("text") or "")) and not ROMAN_PAGE_RE.fullmatch(str(item.get("text") or ""))]
            body_size_by_page[page_number] = median(sizes) if sizes else None

        candidates_by_page: dict[int, list[dict[str, Any]]] = {}
        for candidate in table_candidates:
            candidates_by_page.setdefault(candidate["page"], []).append(candidate)

        # Build canonical table groups.  A one-row candidate near the previous
        # page bottom may be a split header for a reliable body near the next
        # page top.  Each physical table region is consumed exactly once.
        used_table_ids: set[str] = set()
        table_blocks_by_page: dict[int, list[tuple[tuple[float, float, float, float], str]]] = {}
        table_consumed_by_page: dict[int, list[tuple[float, float, float, float]]] = {}

        for candidate in sorted(table_candidates, key=lambda item: (item["page"], item["bbox"][1], item["bbox"][0])):
            if candidate["id"] in used_table_ids or not candidate["reliable"]:
                continue

            group: list[dict[str, Any]] = []
            page_number = candidate["page"]
            page_height = page_sizes[page_number][1]

            # Look for a physical one-row header on the immediately preceding
            # page. It must be near the page bottom and share the same geometry.
            header: dict[str, Any] | None = None
            if candidate["bbox"][1] <= page_height * 0.22:
                previous_page = page_number - 1
                previous_height = page_sizes.get(previous_page, (0.0, 0.0))[1]
                header_candidates = [
                    item for item in candidates_by_page.get(previous_page, [])
                    if item["id"] not in used_table_ids
                    and len(item.get("compacted") or []) == 1
                    and previous_height > 0
                    and item["bbox"][3] >= previous_height * 0.78
                    and _same_table_shape(item, candidate)
                ]
                if header_candidates:
                    header = max(header_candidates, key=lambda item: (_x_overlap_ratio(item["bbox"], candidate["bbox"]), item["bbox"][3]))
                    group.append(header)

            group.append(candidate)

            # Also join a body that itself continues onto following pages.  This
            # is conservative: the previous piece must reach the bottom band and
            # the next piece must begin in the top band with the same columns.
            current = candidate
            while True:
                current_page = current["page"]
                current_height = page_sizes[current_page][1]
                if current["bbox"][3] < current_height * 0.78:
                    break
                next_page = current_page + 1
                next_height = page_sizes.get(next_page, (0.0, 0.0))[1]
                if not next_height:
                    break
                next_candidates = [
                    item for item in candidates_by_page.get(next_page, [])
                    if item["id"] not in used_table_ids
                    and (item["reliable"] or len(item.get("compacted") or []) == 1)
                    and item["bbox"][1] <= next_height * 0.22
                    and _same_table_shape(current, item)
                ]
                if not next_candidates:
                    break
                nxt = max(next_candidates, key=lambda item: _x_overlap_ratio(current["bbox"], item["bbox"]))
                group.append(nxt)
                current = nxt

            # Render all physical pieces on one stable logical grid.  When the
            # raw grids match (typical continuation), preserve raw columns. If
            # office-generated header/body grids differ, use compacted logical
            # columns and project narrower merged-cell continuation rows by x.
            target = max(group, key=lambda item: (max((len(row) for row in item.get("compacted") or []), default=0), int(item.get("raw_width") or 0)))
            target_compact_width = max((len(row) for row in target.get("compacted") or []), default=0)
            target_raw_width = int(target.get("raw_width") or 0)
            use_raw_grid = target_raw_width >= 2 and target_compact_width == target_raw_width
            if use_raw_grid:
                target_width = target_raw_width
                # Recover raw x starts from logical starts because in raw-grid mode
                # every raw column is also a logical column.
                target_x = list(target.get("logical_x_starts") or [])
            else:
                target_width = target_compact_width
                target_x = list(target.get("logical_x_starts") or [])

            combined: list[list[str]] = []
            for item in group:
                if use_raw_grid and int(item.get("raw_width") or 0) == target_raw_width:
                    rows_for_item = _normalise_raw_rows(item.get("rows") or [], target_raw_width)
                else:
                    rows_for_item = [list(row) for row in item.get("compacted") or []]
                    item_x = list(item.get("logical_x_starts") or [])
                    if target_x and item_x and len(rows_for_item[0]) != target_width:
                        rows_for_item = _project_logical_rows(rows_for_item, item_x, target_x)
                    rows_for_item = [row + [""] * (target_width - len(row)) for row in rows_for_item]
                if not rows_for_item:
                    continue
                if combined and [normalize_line(cell) for cell in rows_for_item[0]] == [normalize_line(cell) for cell in combined[0]]:
                    rows_for_item = rows_for_item[1:]
                combined.extend(rows_for_item)

            if not combined:
                continue
            markdown = _logical_rows_to_markdown(combined)
            if not markdown:
                continue

            anchor = header or candidate
            table_blocks_by_page.setdefault(anchor["page"], []).append((anchor["bbox"], markdown))
            for item in group:
                used_table_ids.add(item["id"])
                table_consumed_by_page.setdefault(item["page"], []).append(item["bbox"])

        order = 0
        for page_number, page in enumerate(pdf.pages, start=1):
            line_items = line_items_by_page.get(page_number, [])
            image_regions = image_regions_by_page.get(page_number, [])
            table_regions = table_consumed_by_page.get(page_number, [])

            # Recover large bordered code/config regions as one canonical block.
            box_regions: list[tuple[tuple[float, float, float, float], str]] = []
            for rect in page.rects:
                try:
                    region = (float(rect["x0"]), float(rect["top"]), float(rect["x1"]), float(rect["bottom"]))
                except (KeyError, TypeError, ValueError):
                    continue
                width = region[2] - region[0]
                height = region[3] - region[1]
                if width < page.width * 0.45 or height < 24 or height > page.height * 0.55:
                    continue
                if any(_iou(region, table_region) >= 0.5 for table_region in table_regions):
                    continue
                if any(_iou(region, image_region) >= 0.5 for image_region in image_regions):
                    continue
                contained = [item for item in line_items if _inside(item["bbox"], region)]
                if len(contained) < 2:
                    continue
                body = "\n".join(item["text"] for item in sorted(contained, key=lambda item: item["top"]))
                if _looks_code_like(body):
                    box_regions.append((region, body))

            canonical_boxes: list[tuple[tuple[float, float, float, float], str]] = []
            for region, body in sorted(box_regions, key=lambda item: ((item[0][2]-item[0][0])*(item[0][3]-item[0][1]), item[0][1])):
                if any(_iou(region, existing) >= 0.8 for existing, _ in canonical_boxes):
                    continue
                canonical_boxes.append((region, body))

            consumed_regions = list(table_regions) + [region for region, _ in canonical_boxes]
            positioned: list[tuple[float, float, Block]] = []
            for item in line_items:
                if any(_inside(item["bbox"], region) for region in consumed_regions):
                    continue
                text = item["text"]
                if PAGE_NUMBER_RE.fullmatch(text) or ROMAN_PAGE_RE.fullmatch(text):
                    continue
                in_toc = page_number in toc_pages
                heading = _layout_heading_info(
                    text,
                    font_size=item.get("font_size"),
                    body_size=body_size_by_page.get(page_number),
                    bold_fraction=float(item.get("bold_fraction") or 0.0),
                    in_toc=in_toc,
                )
                kind = "toc" if in_toc else ("heading" if heading else "text")
                heading_level = heading[0] if heading else None
                canonical_text = heading[1] if heading else text
                bbox = item["bbox"]
                positioned.append((bbox[1] if bbox else item["top"], bbox[0] if bbox else 0.0, Block(canonical_text, page_number, heading_level, bbox, order, kind)))
                order += 1

            for region, markdown in table_blocks_by_page.get(page_number, []):
                positioned.append((region[1], region[0], Block(markdown, page_number, None, region, order, "table")))
                order += 1
            for region, body in canonical_boxes:
                positioned.append((region[1], region[0], Block(body, page_number, None, region, order, "box")))
                order += 1

            seen_page: set[tuple[str, int]] = set()
            for _top, _left, block in sorted(positioned, key=lambda item: (item[0], item[1], item[2].order)):
                key = (block.text, block.heading_level or 0)
                if key in seen_page and block.kind == "heading":
                    continue
                seen_page.add(key)
                blocks.append(block)

    # Remove repeated running headers/footers after all pages are known.
    margin_counts: Counter[str] = Counter()
    margin_pages: dict[str, set[int]] = {}
    for block in blocks:
        size = page_sizes.get(block.page)
        if not size or not block.bbox:
            continue
        height = size[1]
        in_margin = block.bbox[1] <= height * 0.08 or block.bbox[3] >= height * 0.92
        if in_margin and len(block.text) <= 120:
            margin_pages.setdefault(block.text, set()).add(block.page)
    for text, pages_seen in margin_pages.items():
        margin_counts[text] = len(pages_seen)
    repeated = {text for text, count in margin_counts.items() if count >= 3}
    if repeated:
        blocks = [block for block in blocks if not (block.text in repeated and block.bbox and (block.bbox[1] <= page_sizes[block.page][1] * 0.08 or block.bbox[3] >= page_sizes[block.page][1] * 0.92))]
    return blocks, page_sizes, source_image_occurrences

def extract_page_lines(pdf_path: Path) -> list[list[str]]:
    """Compatibility wrapper returning page text in canonical reading order."""
    blocks, page_sizes, _source_images = _extract_blocks_from_pdf(Path(pdf_path))
    pages: list[list[str]] = [[] for _ in range(max(page_sizes, default=0))]
    for block in blocks:
        pages[block.page - 1].append(TABLE_PREFIX + block.text if block.kind == "table" else block.text)
    return pages


def repeated_margin_lines(pages: list[list[str]]) -> set[str]:
    counts: Counter[str] = Counter()
    for lines in pages:
        nonempty = [line for line in lines if line]
        counts.update(set(nonempty[:2] + nonempty[-2:]))
    return {line for line, count in counts.items() if count >= 3 and len(line) <= 80 and not _heading_info(line)}


def join_wrapped(left: str, right: str) -> str:
    if not left:
        return right
    if left[-1:].isascii() and left[-1:].isalnum() and right[:1].isascii() and right[:1].isalnum():
        return f"{left} {right}"
    return left + right


def lines_to_blocks(pages: list[list[str]]) -> list[Block]:
    """Compatibility parser for pre-extracted line lists."""
    margin_lines = repeated_margin_lines(pages)
    blocks: list[Block] = []
    order = 0
    for page_number, raw_lines in enumerate(pages, start=1):
        paragraph = ""

        def flush() -> None:
            nonlocal paragraph, order
            if paragraph.strip():
                blocks.append(Block(paragraph.strip(), page_number, None, None, order, "text"))
                order += 1
            paragraph = ""

        for raw in raw_lines:
            line = normalize_line(raw)
            if not line or line in margin_lines or PAGE_NUMBER_RE.fullmatch(line):
                flush()
                continue
            if line.startswith(TABLE_PREFIX):
                flush()
                blocks.append(Block(line.removeprefix(TABLE_PREFIX), page_number, None, None, order, "table")); order += 1
                continue
            heading = _heading_info(line)
            if heading:
                flush()
                blocks.append(Block(heading[1], page_number, heading[0], None, order, "heading")); order += 1
                continue
            if COMMAND_RE.match(line):
                flush()
                blocks.append(Block(line, page_number, None, None, order, "code")); order += 1
                continue
            if paragraph and paragraph.endswith(END_PUNCTUATION):
                flush()
            paragraph = line if not paragraph else join_wrapped(paragraph, line)
        flush()
    return blocks


def heading_paths(blocks: list[Block]) -> list[tuple[Block, str]]:
    path: dict[int, str] = {}
    result: list[tuple[Block, str]] = []
    for block in blocks:
        if block.heading_level:
            path = {level: value for level, value in path.items() if level < block.heading_level}
            path[block.heading_level] = block.text
        ordered = [path[level] for level in sorted(path)]
        result.append((block, " > ".join(ordered)))
    return result


def _render_block(block: Block) -> str:
    if block.heading_level:
        return f"{'#' * block.heading_level} {_protect_angle_tokens(block.text)}"
    if block.kind in {"box", "code"}:
        return "```text\n" + block.text.strip("\n") + "\n```"
    if block.kind == "table":
        return block.text
    return _protect_angle_tokens(block.text)


def render_markdown(document: str, blocks: list[Block]) -> str:
    lines = [f"# {document.removesuffix('.pdf')}", ""]
    for block in blocks:
        lines.extend([_render_block(block), ""])
    return "\n".join(lines).strip() + "\n"


def split_chunks(document: str, blocks: list[Block], max_chars: int) -> list[dict]:
    """Chunk once from canonical blocks; headings are never dropped or copied."""
    chunks: list[dict] = []
    current: list[str] = []
    current_section: str | None = None
    current_page: int | None = None

    def emit() -> None:
        nonlocal current
        content = "\n\n".join(current).strip()
        if content:
            chunks.append({
                "document": document,
                "section": current_section,
                "heading_path": current_section,
                "page": current_page,
                "chunk_id": f"chunk-{len(chunks) + 1:04d}",
                "content": content,
            })
        current = []

    for block, section in heading_paths(blocks):
        if block.kind == "toc":
            continue
        rendered = _render_block(block)
        if block.heading_level:
            emit()
            current_section = section or None
            current_page = block.page
            current = [rendered]
            continue
        candidate = "\n\n".join(current + [rendered])
        if current and len(candidate) > max_chars:
            emit()
            current_page = block.page
            current_section = section or current_section
        if not current:
            current_page = block.page
            current_section = section or current_section
        current.append(rendered)
    emit()
    return chunks


def parse_pdf(pdf_path: Path, *, max_chars: int = 1800) -> ParsedDocument:
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if max_chars < 400:
        raise ValueError("max_chars should be at least 400")
    document = pdf_path.name
    blocks, page_sizes, source_images = _extract_blocks_from_pdf(pdf_path)
    return ParsedDocument(document, blocks, split_chunks(document, blocks, max_chars), render_markdown(document, blocks), page_sizes, str(pdf_path.resolve()), source_images)


__all__ = ["Block", "ParsedDocument", "compact_table_rows", "extract_page_lines", "heading_paths", "join_wrapped", "lines_to_blocks", "normalize_line", "parse_pdf", "render_markdown", "split_chunks", "table_to_markdown"]
