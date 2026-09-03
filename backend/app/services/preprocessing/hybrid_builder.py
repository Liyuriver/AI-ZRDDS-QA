"""Build the local hybrid knowledge dataset in one small module."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber

from app.services.preprocessing.layout_model import build_page_blocks, mark_table_header_visuals, render_page_blocks


def _image_markdown(item: dict[str, Any], output_dir: Path) -> str:
    source = item.get("image_path") or item.get("path")
    if not source:
        return ""
    source_path = Path(source)
    if not source_path.is_file():
        return ""
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    # The output name is keyed by the logical record, not by the source
    # basename. Different MinerU exports can contain duplicate basenames;
    # basename-based copying overwrites one image and makes validation
    # report the wrong record as inserted.
    target = image_dir / f"{item.get('image_id', source_path.stem)}{source_path.suffix.lower() or '.jpg'}"
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    caption = item.get("caption") or item.get("vlm", {}).get("caption") or item.get("image_id", "image")
    vlm = item.get("vlm", {})
    bbox = item.get("bbox") or []
    thin_table_fragment = len(bbox) == 4 and (bbox[3] - bbox[1]) / max(bbox[2] - bbox[0], 1) < 0.07
    if vlm.get("image_type") == "table_image" or (item.get("mineru_type") == "table" and (not vlm.get("image_type") or vlm.get("image_type") == "unknown") and thin_table_fragment):
        return ""
    visual_lines = [f"![{caption}](images/{target.name})"]
    code_content = vlm.get("code_content")
    if not code_content and vlm.get("image_type") == "code_or_config" and any(str(value).startswith(("QT ", "TARGET ", "CONFIG ", "TEMPLATE ", "SOURCES ", "HEADERS ", "INCLUDEPATH ", "LIBS ", "DEFINES ")) for value in vlm.get("key_information", [])):
        code_content = "\n".join(str(value) for value in vlm.get("key_information", []))
    if code_content:
        code_content = str(code_content).replace("$$(", "$(")
        code_block = "```qmake\n" + str(code_content).strip("\n") + "\n```"
    else:
        code_block = ""
    verified_values = [value for value in vlm.get("technical_values_review", []) if value.get("verified_value") is not None and not value.get("needs_review")]
    if vlm.get("description") or vlm.get("key_information") or verified_values:
        visual_lines.append("\n**图示信息：**")
        if vlm.get("description"):
            visual_lines.append(f"\n- {_safe_explanation(str(vlm['description']))}")
        if not code_content:
            for value in vlm.get("key_information", []):
                visual_lines.append(f"\n- {_safe_explanation(str(value))}")
        for value in verified_values:
            prefix = f"{value.get('label')}：" if value.get("label") else "关键值："
            visual_lines.append(f"\n- {prefix}{_inline_code(value['verified_value'])}")
    visual_body = "".join(visual_lines)
    # Keep image and explanation in a visual block. Keep the code fence at
    # top level so Markdown renderers show it as an independent code box.
    boxed = "\n".join(f"> {line}" if line else ">" for line in visual_body.splitlines())
    return boxed + ("\n\n" + code_block if code_block else "")


def rewrite_recovered_visual_anchors(markdown_path: Path, visuals: dict[str, dict[str, Any]], root: Path) -> dict[str, int]:
    """Replace resolved UNRESOLVED_VISUAL anchors in-place and remove duplicates.

    Recovery scripts operate after page rendering, so the original layout
    already contains a stable image_id anchor.  This function deliberately
    uses that identity rather than page/chapter/image-number rules.
    """
    markdown_path = Path(markdown_path)
    root = Path(root)
    text = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
    valid: dict[str, dict[str, Any]] = {}
    for image_id, item in visuals.items():
        path = root / str(item.get("path") or "")
        if not image_id or not path.is_file():
            continue
        if item.get("binding_status") not in (None, "resolved"):
            continue
        if item.get("resolution_status") not in (None, "resolved"):
            continue
        valid[image_id] = item

    def block(item: dict[str, Any]) -> list[str]:
        image_id = str(item.get("image_id") or "image")
        path = str(item.get("path") or "").replace("\\", "/")
        rel = path[path.find("images/"):] if "images/" in path else path
        caption = str(item.get("caption") or (item.get("vlm") or {}).get("caption") or "源文档图像").strip()
        description = str((item.get("vlm") or {}).get("description") or item.get("description") or "").strip()
        result = [f"> ![{caption}]({rel})", ">"]
        if description:
            result.extend(["> **图示信息：**", ">", f"> - {description}"])
        return result

    replaced = 0
    lines = text.splitlines()
    placeholder = re.compile(r"^\s*<!--\s*UNRESOLVED_VISUAL\s+image_id=([^\s]+)[^>]*-->\s*$")
    expanded: list[str] = []
    for line in lines:
        match = placeholder.match(line)
        image_id = match.group(1) if match else ""
        if image_id in valid:
            expanded.extend(block(valid[image_id]))
            replaced += 1
        else:
            expanded.append(line)

    # Keep the first valid visual block (normally the just-replaced anchor)
    # and discard later copies, including old end-of-document append blocks.
    image_ref = re.compile(r"images/([^\s)]+)")
    seen: set[str] = set()
    output: list[str] = []
    removed = 0
    index = 0
    while index < len(expanded):
        line = expanded[index]
        ref = image_ref.search(line)
        image_id = Path(ref.group(1)).stem if ref else ""
        if image_id in valid:
            if image_id in seen:
                removed += 1
                index += 1
                while index < len(expanded) and (expanded[index].startswith(">") or not expanded[index].strip()):
                    index += 1
                continue
            seen.add(image_id)
        output.append(line)
        index += 1

    result = "\n".join(output).rstrip() + "\n"
    markdown_path.write_text(result, encoding="utf-8")
    refs = re.findall(r"!\[[^]]*\]\(images/([^)]*)\)", result)
    return {
        "resolved_placeholder_candidates": sum(1 for line in lines if (m := placeholder.match(line)) and m.group(1) in valid),
        "placeholder_replaced": replaced,
        "end_appended_visuals_removed": removed,
        "duplicate_image_insertions": len(refs) - len(set(refs)),
        "remaining_unresolved_visuals": len(re.findall(r"UNRESOLVED_VISUAL", result)),
    }


def _inline_code(value: Any) -> str:
    return f"`{str(value).replace('`', '')}`"


def _safe_explanation(value: str) -> str:
    if any(token in value for token in ("\\", "$", "%(")):
        return _inline_code(value)
    technical = re.compile(r"(?<![`\\])(?:\$\([^)]+\)(?:/[A-Za-z0-9_.+-]+)+|(?:/[A-Za-z0-9_.+-]+){2,}|\b[A-Za-z_][\w]*\.(?:exe|dll|lib|h|cpp|c|sh|lic|bmp)\b)")
    # Match against the original dollar sign; escape only dollars that remain
    # outside an inline-code span.
    value = value.replace(r"\$", "$")
    rendered = technical.sub(lambda match: _inline_code(match.group(0)), value)
    parts = rendered.split("`")
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("$", r"\$")
    return "`".join(parts)


def _protect_qmake_quote_macros(line: str) -> str:
    """Wrap balanced qmake $$quote(...) expressions before Markdown sees $$ ."""
    marker = "$$quote("
    cursor = 0
    while True:
        start = line.find(marker, cursor)
        if start < 0:
            return line
        depth = 0
        end = None
        for index in range(start + len(marker) - 1, len(line)):
            if line[index] == "(":
                depth += 1
            elif line[index] == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            return line
        expression = line[start:end]
        line = line[:start] + _inline_code(expression) + line[end:]
        cursor = start + len(expression) + 2


def _protect_source_technical_values(markdown: str) -> str:
    """Protect source macros/paths without touching table rows or code blocks."""
    lines = []
    in_fence = False
    # Do not wrap Windows paths here. Paths such as
    # C:\Program Files (x86)\... contain spaces; a token regex would split
    # them into several backtick spans. Raw Windows paths render correctly in
    # Markdown, so only macros and Unix-style paths are protected.
    path = re.compile(r"(?<![`])(?:\$\([^)]+\)(?:[\\/][A-Za-z0-9_.%()+-]+)+|(?:/[A-Za-z0-9_.+-]+){2,}|\$\([^)]+\))")
    # Protect placeholders/XML-like tokens while preserving intentional Markdown
    # HTML used by our table renderer (currently only <br>).
    angle = re.compile(r"(?<!`)<(?!/?br\s*/?>)(?![!])[^<>\n]{1,200}>(?!`)", re.IGNORECASE)
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("> ```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue
        line = _protect_qmake_quote_macros(line)
        line = angle.sub(lambda match: _inline_code(match.group(0)), line)
        parts = line.split("`")
        for index in range(0, len(parts), 2):
            parts[index] = path.sub(lambda match: _inline_code(match.group(0)), parts[index])
        line = "`".join(parts)
        lines.append(line)
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def _technical_values(value: Any, label: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        result = []
        for key, nested in value.items():
            result.extend(_technical_values(nested, str(key)))
        return result
    if isinstance(value, list):
        result = []
        for nested in value:
            result.extend(_technical_values(nested, label))
        return result
    if value is None:
        return []
    return [(label, str(value))]


def _is_table_excluded(match: dict[str, Any], vlm: dict[str, Any]) -> bool:
    """Exclude a true table visual or a geometry-confirmed table header fragment."""
    caption = str(match.get("caption") or vlm.get("caption") or "")
    formal_figure = bool(re.match(r"^(?:(?:图|\u037c)\s*\d+|Figure\s+\d+|Fig\.\s*\d+)\b", caption, re.IGNORECASE))
    return match.get("record_status") == "table_header_excluded" or (vlm.get("image_type") == "table_image" and not formal_figure)



def _normalized_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    scale = 1.0 if max(abs(item) for item in box) <= 1.5 else 1000.0
    box = tuple(max(0.0, min(1.0, item / scale)) for item in box)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _normalized_iou(left: tuple[float, float, float, float] | None, right: tuple[float, float, float, float] | None) -> float:
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


def _centre_inside_norm(inner: tuple[float, float, float, float] | None, outer: tuple[float, float, float, float] | None) -> bool:
    if not inner or not outer:
        return False
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]



def _intersection_cover(left: tuple[float, float, float, float] | None, right: tuple[float, float, float, float] | None) -> tuple[float, float]:
    if not left or not right:
        return 0.0, 0.0
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0
    inter = (x1 - x0) * (y1 - y0)
    la = max((left[2] - left[0]) * (left[3] - left[1]), 1e-9)
    ra = max((right[2] - right[0]) * (right[3] - right[1]), 1e-9)
    return inter / la, inter / ra


def _covered_by_canonical_source(source_box: tuple[float, float, float, float], page: int, matches: list[dict[str, Any]]) -> bool:
    """Detect a small native source image wholly contained by a known visual."""
    source_area = max((source_box[2] - source_box[0]) * (source_box[3] - source_box[1]), 1e-9)
    for match in matches:
        if int(match.get("page") or 0) != page:
            continue
        canonical_box = _normalized_bbox(match.get("bbox"))
        if not canonical_box:
            continue
        canonical_area = max((canonical_box[2] - canonical_box[0]) * (canonical_box[3] - canonical_box[1]), 1e-9)
        source_cover, canonical_cover = _intersection_cover(source_box, canonical_box)
        contains = (
            source_box[0] >= canonical_box[0]
            and source_box[1] >= canonical_box[1]
            and source_box[2] <= canonical_box[2]
            and source_box[3] <= canonical_box[3]
        )
        if source_area / canonical_area <= 0.30 and (contains or source_cover >= 0.80 or canonical_cover >= 0.80):
            return True
    return False




def _source_text_context_for_page(parsed: Any, page: int) -> str:
    """Return nearby source-backed text for conservative code correction.

    Context is evidence only and is deliberately page-local. Adjacent pages can
    contain similarly named variables and must not trigger automatic repair.
    """
    parts: list[str] = []
    for block in getattr(parsed, "blocks", []) or []:
        block_page = int(getattr(block, "page", 0) or 0)
        if block_page != int(page):
            continue
        text = str(getattr(block, "text", "") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _chunk_meta_for_page(parsed: Any, page: int) -> tuple[str | None, str | None]:
    candidates = [chunk for chunk in getattr(parsed, "chunks", []) if page in (chunk.get("source_pages") or [chunk.get("page")])]
    if len(candidates) == 1:
        return candidates[0].get("chunk_id"), candidates[0].get("section")
    return None, None


def _bind_visual_chunks(parsed: Any, matches: list[dict[str, Any]], enrichments: dict[str, dict[str, Any]], codes: list[dict[str, Any]]) -> None:
    from app.services.preprocessing.image_context_matcher import resolve_visual_chunk
    from app.services.preprocessing.layout_model import bind_source_figure_captions
    chunks = getattr(parsed, "chunks", [])
    blocks = getattr(parsed, "blocks", [])
    bind_source_figure_captions(parsed, matches, enrichments)
    for item in [*matches, *codes]:
        if item in matches:
            image_id = str(item.get("image_id") or "")
            visual = dict(item)
            visual["caption"] = item.get("caption") or (enrichments.get(image_id, {}) or {}).get("caption")
        else:
            visual = item
        binding = resolve_visual_chunk(visual, chunks, blocks, getattr(parsed, "page_sizes", {}))
        item["chunk_id"] = binding.get("chunk_id")
        item["section"] = binding.get("section")
        item["binding_status"] = binding.get("binding_status")
        item["binding_reason"] = binding.get("binding_reason")
        item["binding_score"] = binding.get("binding_score")
        item["needs_review"] = binding.get("binding_status") != "resolved"



def _overlapping_code_candidate(match: dict[str, Any], code_matches: list[dict[str, Any]]) -> str | None:
    """Return the strongest overlapping MinerU text candidate, if any."""
    page = int(match.get("page") or 0)
    visual_box = _normalized_bbox(match.get("bbox"))
    if not visual_box:
        return None
    best: tuple[float, str] | None = None
    for code in code_matches:
        if int(code.get("page") or 0) != page:
            continue
        code_box = _normalized_bbox(code.get("bbox"))
        if not code_box:
            continue
        iou = _normalized_iou(visual_box, code_box)
        left_cover, right_cover = _intersection_cover(visual_box, code_box)
        score = max(iou, left_cover, right_cover)
        if score < 0.30:
            continue
        candidate = str(code.get("code_content") or code.get("mineru_code_content") or "").strip()
        if candidate and (best is None or score > best[0]):
            best = (score, candidate)
    return best[1] if best else None


def _enrich_late_source_visuals(
    parsed: Any,
    matches: list[dict[str, Any]],
    enrichments: dict[str, dict[str, Any]],
    code_matches: list[dict[str, Any]],
) -> None:
    """Run the normal VLM path for native PDF images recovered after MinerU.

    V9 recovered PDF XObjects inside build_dataset(), after the normal VLM pass,
    and left them as ``source_recovered_without_vlm``.  Those images therefore
    rendered with no 图示信息.  Only those late records are handled here; already
    enriched MinerU images are untouched.
    """
    from app.services.preprocessing.image_vlm import enrich_image

    document = str(getattr(parsed, "document", "document.pdf"))
    for match in matches:
        image_id = str(match.get("image_id") or "")
        if not image_id:
            continue
        current = dict(enrichments.get(image_id) or {})
        if str(current.get("parse_status") or "") != "source_recovered_without_vlm":
            continue

        source = Path(str(match.get("path") or ""))
        if not source.is_absolute() and match.get("mineru_root"):
            source = Path(str(match.get("mineru_root"))) / source
        if not source.is_file():
            current["parse_status"] = "source_recovered_vlm_failed"
            current["needs_review"] = True
            current["error"] = "late recovered source image is missing"
            enrichments[image_id] = current
            continue

        analysis_source = source
        temporary_analysis: Path | None = None
        try:
            if source.suffix.lower() == ".svg":
                temporary_analysis = _vector_analysis_png(source)
                analysis_source = temporary_analysis
            result = enrich_image(
                analysis_source,
                document=document,
                section=str(match.get("section") or "") or None,
                context_before=_source_text_context_for_page(parsed, int(match.get("page") or 0)),
                context_after="",
                mineru_ocr=_overlapping_code_candidate(match, code_matches),
            )
        except Exception as exc:
            result = {
                "image_type": current.get("image_type") or "unknown",
                "parse_status": "failed",
                "needs_review": True,
                "error": str(exc),
            }
        finally:
            if temporary_analysis is not None:
                temporary_analysis.unlink(missing_ok=True)

        merged = dict(current)
        if isinstance(result, dict):
            merged.update(result)
        # An explicit caption extracted from the source PDF is authoritative.
        # VLM may describe the pixels, but must not rename a known source figure.
        if current.get("caption") and current.get("caption_source") == "pdf_explicit_figure_caption":
            merged["caption"] = current["caption"]
        elif current.get("caption") and not merged.get("caption"):
            merged["caption"] = current["caption"]
        if merged.get("parse_status") in {"vlm_disabled", "offline_mock"}:
            merged["parse_status"] = "source_recovered_vlm_disabled"
            merged["needs_review"] = True
        elif merged.get("parse_status") != "success":
            merged["parse_status"] = "source_recovered_vlm_failed"
            merged["needs_review"] = True
        enrichments[image_id] = merged


def _filter_names(value: Any) -> set[str]:
    """Return normalized PDF stream filter names without changing pixels."""
    if value is None:
        return set()
    items = value if isinstance(value, (list, tuple)) else [value]
    return {str(item).strip("/'") for item in items}


def _extract_embedded_occurrence(
    source_path: Path,
    occurrence: dict[str, Any],
    target_stem: Path,
    *,
    fitz_doc: Any | None = None,
    plumber_pdf: Any | None = None,
) -> Path | None:
    """Extract one PDF image XObject at its native pixel resolution.

    This function NEVER renders a PDF page.  The preferred path uses
    PyMuPDF's extract_image(xref), which returns the embedded image bytes (or a
    native-resolution PNG for Flate/soft-mask images).  A pdfplumber/Pillow
    fallback handles common JPEG/JPX/8-bit RGB/Gray/CMYK streams without page
    rasterization.
    """
    xref = occurrence.get("xref")
    if xref and fitz_doc is not None:
        try:
            info = fitz_doc.extract_image(int(xref))
            payload = info.get("image") if isinstance(info, dict) else None
            if payload:
                ext = str(info.get("ext") or "png").lower().lstrip(".")
                if ext == "jpeg":
                    ext = "jpg"
                target = target_stem.with_suffix(f".{ext}")
                target.write_bytes(payload)
                return target
        except Exception:
            pass

    # No-render fallback for environments without PyMuPDF.  It reconstructs
    # the image directly from the PDF image stream at srcsize.
    if plumber_pdf is None:
        return None
    page_number = int(occurrence.get("page") or 0)
    occurrence_number = int(occurrence.get("occurrence_index") or 0)
    if page_number < 1 or page_number > len(plumber_pdf.pages) or occurrence_number < 1:
        return None
    page_images = plumber_pdf.pages[page_number - 1].images
    if occurrence_number > len(page_images):
        return None
    image = page_images[occurrence_number - 1]
    stream = image.get("stream")
    if stream is None:
        return None
    attrs = getattr(stream, "attrs", {}) or {}
    filters = _filter_names(attrs.get("Filter"))
    try:
        if "DCTDecode" in filters:
            target = target_stem.with_suffix(".jpg")
            target.write_bytes(stream.get_rawdata())
            return target
        if "JPXDecode" in filters:
            target = target_stem.with_suffix(".jp2")
            target.write_bytes(stream.get_rawdata())
            return target

        from PIL import Image

        width = int(attrs.get("Width") or image.get("srcsize", [0, 0])[0] or 0)
        height = int(attrs.get("Height") or image.get("srcsize", [0, 0])[1] or 0)
        bits = int(attrs.get("BitsPerComponent") or 8)
        if width <= 0 or height <= 0 or bits != 8:
            return None
        colorspace = str(attrs.get("ColorSpace") or "DeviceRGB").strip("/'")
        mode = {"DeviceRGB": "RGB", "DeviceGray": "L", "DeviceCMYK": "CMYK"}.get(colorspace)
        if mode is None:
            return None
        decoded = stream.get_data()
        expected = width * height * len(Image.new(mode, (1, 1)).getbands())
        if len(decoded) < expected:
            return None
        native = Image.frombytes(mode, (width, height), decoded[:expected])
        if mode == "CMYK":
            native = native.convert("RGB")
        target = target_stem.with_suffix(".png")
        native.save(target, format="PNG")
        return target
    except Exception:
        return None


def _explicit_figure_captions(parsed: Any) -> list[dict[str, Any]]:
    """Return real body figure captions (not TOC references or prose mentions).

    This is deliberately source-geometry based.  A caption must be a short,
    centered source block whose whole line starts with ``图 N``.  This avoids
    document-specific figure numbers while rejecting prose such as
    ``图 56 为 ...`` and front-matter figure-directory entries.
    """
    result: list[dict[str, Any]] = []
    for block in getattr(parsed, "blocks", []) or []:
        if str(getattr(block, "kind", "") or "") == "toc":
            continue
        text = str(getattr(block, "text", "") or "").strip()
        # Some PDFs expose the Chinese ``图`` glyph as ``ͼ`` through the
        # embedded font map. Treat that equivalent OCR form identically.
        match = re.match(r"^(?:图|\u037c)\s*(\d+)\s*(?:[-－]\s*(\d+))?\s*([^\n]{1,40})$", text)
        box = getattr(block, "bbox", None)
        page = int(getattr(block, "page", 0) or 0)
        if not match or not box or page <= 0:
            continue
        page_size = getattr(parsed, "page_sizes", {}).get(page)
        if not page_size:
            continue
        width, _height = page_size
        centre_x = (float(box[0]) + float(box[2])) / 2.0
        if abs(centre_x - width / 2.0) > width * 0.22:
            continue
        if float(box[2]) - float(box[0]) > width * 0.48:
            continue
        figure_label = f"{match.group(1)}-{match.group(2)}" if match.group(2) else match.group(1)
        result.append({
            "page": page,
            "figure_number": int(match.group(1)),
            "figure_label": figure_label,
            "caption": text,
            "bbox": tuple(float(value) for value in box),
        })
    return result


def _match_page_bbox(parsed: Any, match: dict[str, Any]) -> tuple[float, float, float, float] | None:
    page = int(match.get("page") or 0)
    size = getattr(parsed, "page_sizes", {}).get(page)
    norm = _normalized_bbox(match.get("bbox"))
    if not size or not norm:
        return None
    width, height = size
    return norm[0] * width, norm[1] * height, norm[2] * width, norm[3] * height


def _caption_is_already_visual(parsed: Any, caption: dict[str, Any], matches: list[dict[str, Any]]) -> bool:
    """Check whether a real image occurrence already owns this source caption."""
    page = int(caption["page"])
    caption_box = tuple(caption["bbox"])
    page_size = getattr(parsed, "page_sizes", {}).get(page, (1.0, 1.0))
    max_gap = max(40.0, page_size[1] * 0.09)
    for match in matches:
        if int(match.get("page") or 0) != page:
            continue
        visual = _match_page_bbox(parsed, match)
        if not visual:
            continue
        below_gap = caption_box[1] - visual[3]
        above_gap = visual[1] - caption_box[3]
        if -8.0 <= below_gap <= max_gap:
            distance_ok = True
        elif 0.0 <= above_gap <= max_gap * 0.55:
            distance_ok = True
        else:
            distance_ok = False
        if not distance_ok:
            continue
        overlap = max(0.0, min(visual[2], caption_box[2]) - max(visual[0], caption_box[0]))
        denom = max(min(visual[2] - visual[0], caption_box[2] - caption_box[0]), 1e-9)
        centre_dx = abs(((visual[0] + visual[2]) / 2.0) - ((caption_box[0] + caption_box[2]) / 2.0))
        if overlap / denom >= 0.15 or centre_dx <= page_size[0] * 0.24:
            return True
    return False


def _vector_crop_bbox(page: Any, caption_box: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    """Find the vector drawing group immediately above one explicit caption.

    The grouping is generic: drawings are clustered vertically and the nearest
    substantial cluster above the caption is selected.  No page/figure number
    is special-cased.
    """
    page_rect = page.rect
    caption_top = float(caption_box[1])
    search_top = max(0.0, caption_top - page_rect.height * 0.65)
    records: list[tuple[float, float, float, float]] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = map(float, (rect.x0, rect.y0, rect.x1, rect.y1))
        if y1 > caption_top + 3.0 or y1 < search_top:
            continue
        if max(x1 - x0, y1 - y0) < 0.35:
            continue
        records.append((x0, y0, x1, y1))
    if not records:
        return None

    # Merge nearby vertical bands.  A ~30pt break separates independent page
    # structures while keeping arrows/boxes/text-decoration belonging to one
    # sequence/architecture diagram together.
    records.sort(key=lambda value: (value[1], value[0]))
    gap_limit = max(20.0, min(32.0, page_rect.height * 0.038))
    clusters: list[dict[str, Any]] = []
    for rect in records:
        if not clusters or rect[1] > clusters[-1]["y1"] + gap_limit:
            clusters.append({"x0": rect[0], "y0": rect[1], "x1": rect[2], "y1": rect[3], "count": 1})
        else:
            cluster = clusters[-1]
            cluster["x0"] = min(cluster["x0"], rect[0])
            cluster["y0"] = min(cluster["y0"], rect[1])
            cluster["x1"] = max(cluster["x1"], rect[2])
            cluster["y1"] = max(cluster["y1"], rect[3])
            cluster["count"] += 1

    candidates = []
    max_caption_gap = max(70.0, page_rect.height * 0.13)
    for cluster in clusters:
        width = cluster["x1"] - cluster["x0"]
        height = cluster["y1"] - cluster["y0"]
        gap = caption_top - cluster["y1"]
        if gap < -4.0 or gap > max_caption_gap:
            continue
        if cluster["count"] < 2 or width < page_rect.width * 0.11 or height < page_rect.height * 0.025:
            continue
        candidates.append((gap, -cluster["count"], cluster))
    if not candidates:
        return None
    cluster = min(candidates, key=lambda item: (item[0], item[1]))[2]

    # Include nearby PDF text labels that are inside the diagram band.  This
    # keeps node names / arrow labels without pulling in surrounding prose.
    x0, y0, x1, y1 = cluster["x0"], cluster["y0"], cluster["x1"], cluster["y1"]
    # Eligibility is measured against the original drawing band, not the
    # progressively enlarged crop.  Otherwise one nearby prose line can pull
    # in the previous line and cascade into a whole paragraph.
    base_x0, base_y0, base_x1, base_y1 = x0, y0, x1, y1
    for block in page.get_text("blocks"):
        bx0, by0, bx1, by1 = map(float, block[:4])
        if by1 < base_y0 - 6.0 or by0 > min(caption_top - 3.0, base_y1 + 10.0):
            continue
        centre_x = (bx0 + bx1) / 2.0
        if base_x0 - 28.0 <= centre_x <= base_x1 + 28.0:
            x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)

    pad_x = max(8.0, page_rect.width * 0.012)
    pad_y = max(7.0, page_rect.height * 0.009)
    return (
        max(0.0, x0 - pad_x),
        max(0.0, y0 - pad_y),
        min(float(page_rect.width), x1 + pad_x),
        min(caption_top - 2.0, y1 + pad_y),
    )


def _write_cropped_vector_svg(page: Any, crop: tuple[float, float, float, float], target: Path) -> bool:
    """Save a source-vector crop as SVG; no page rasterization is used."""
    try:
        svg = page.get_svg_image(text_as_path=True)
        x0, y0, x1, y1 = crop
        width, height = x1 - x0, y1 - y0
        if width <= 1 or height <= 1:
            return False
        svg = re.sub(r'(<svg\b[^>]*?)width="[^"]+"', rf'\1width="{width:.2f}"', svg, count=1)
        svg = re.sub(r'(<svg\b[^>]*?)height="[^"]+"', rf'\1height="{height:.2f}"', svg, count=1)
        svg = re.sub(r'(<svg\b[^>]*?)viewBox="[^"]+"', rf'\1viewBox="{x0:.2f} {y0:.2f} {width:.2f} {height:.2f}"', svg, count=1)
        target.write_text(svg, encoding="utf-8")
        return True
    except Exception:
        return False


def _supplement_pdf_vector_figures(
    parsed: Any,
    matches: list[dict[str, Any]],
    enrichments: dict[str, dict[str, Any]],
    output_dir: Path,
) -> None:
    """Recover semantic figures drawn as PDF vectors instead of image XObjects."""
    source_value = getattr(parsed, "source_path", None)
    source_path = Path(source_value) if source_value else None
    if not source_path or not source_path.is_file():
        return
    captions = _explicit_figure_captions(parsed)
    if not captions:
        return
    try:
        import fitz
        document = fitz.open(source_path)
    except Exception:
        return

    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {str(item.get("image_id") or "") for item in matches}
    ordinal_by_key: dict[tuple[int, int], int] = {}
    try:
        for caption in captions:
            if _caption_is_already_visual(parsed, caption, matches):
                continue
            page_number = int(caption["page"])
            if page_number < 1 or page_number > len(document):
                continue
            page = document[page_number - 1]
            crop = _vector_crop_bbox(page, tuple(caption["bbox"]))
            if not crop:
                continue
            key = (page_number, int(caption["figure_number"]))
            ordinal_by_key[key] = ordinal_by_key.get(key, 0) + 1
            suffix = ordinal_by_key[key]
            base_id = f"vector-p{page_number}-fig{caption['figure_number']}"
            image_id = base_id if suffix == 1 else f"{base_id}-{suffix}"
            dedupe = 2
            while image_id in existing_ids:
                image_id = f"{base_id}-{dedupe}"
                dedupe += 1
            existing_ids.add(image_id)
            target = image_dir / f"{image_id}.svg"
            if not _write_cropped_vector_svg(page, crop, target):
                continue

            width, height = getattr(parsed, "page_sizes", {}).get(page_number, (float(page.rect.width), float(page.rect.height)))
            normalized = [crop[0] / width, crop[1] / height, crop[2] / width, crop[3] / height]
            chunk_id, section = _chunk_meta_for_page(parsed, page_number)
            matches.append({
                "image_id": image_id,
                "source_occurrence_id": f"pdf-vector:p{page_number}:fig{caption['figure_number']}:o{suffix}",
                "source_occurrence_status": "source_vector_extracted",
                "source_image_policy": "pdf_vector_svg_no_page_render",
                "path": str(target.resolve()),
                "page": page_number,
                "bbox": normalized,
                "coordinate_space": "normalized_0_1",
                "mineru_type": "pdf_source_vector_figure",
                "caption": caption["caption"],
                "chunk_id": chunk_id,
                "section": section,
                "match_score": 100,
                "match_status": "source_vector_recovered",
                "slot_id": None,
                "slot_status": "not_used",
                "record_status": "candidate",
            })
            enrichments[image_id] = {
                "image_type": "architecture_or_flow",
                "caption": caption["caption"],
                "caption_source": "pdf_explicit_figure_caption",
                "description": "",
                "key_information": [],
                "technical_values": [],
                "needs_review": True,
                "parse_status": "source_recovered_without_vlm",
                "source_image_policy": "pdf_vector_svg_no_page_render",
            }
    finally:
        document.close()


def _vector_analysis_png(source: Path) -> Path:
    """Rasterize only a recovered SVG crop for VLM input, never the PDF page.

    The canonical artifact remains SVG.  This temporary PNG exists solely
    because common multimodal APIs accept raster image MIME types more reliably.
    """
    handle = tempfile.NamedTemporaryFile(prefix="zrdds_vector_vlm_", suffix=".png", delete=False)
    handle.close()
    target = Path(handle.name)
    try:
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=source.read_bytes(), write_to=str(target), output_width=2200, background_color="#ffffff")
        except Exception:
            import fitz
            svg_doc = fitz.open(stream=source.read_bytes(), filetype="svg")
            try:
                page = svg_doc[0]
                scale = max(2.5, min(5.0, 2200.0 / max(float(page.rect.width), 1.0)))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                pix.save(target)
            finally:
                svg_doc.close()
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise

def _supplement_pdf_image_occurrences(
    parsed: Any,
    matches: list[dict[str, Any]],
    enrichments: dict[str, dict[str, Any]],
    output_dir: Path,
) -> None:
    """Use native PDF image occurrences as the canonical visual source.

    MinerU contributes layout/type evidence only.  Every real PDF image
    occurrence is materialized directly from its XObject at native resolution,
    then matched one-to-one to a detector record.  No PDF page is rasterized.
    Identical source images therefore remain separate occurrences when they
    appear more than once in the document.
    """
    occurrences = list(getattr(parsed, "source_image_occurrences", []) or [])
    if not occurrences:
        return

    table_regions: dict[int, list[tuple[float, float, float, float]]] = {}
    for block in getattr(parsed, "blocks", []):
        if getattr(block, "kind", "") != "table":
            continue
        page = int(getattr(block, "page", 0))
        width, height = getattr(parsed, "page_sizes", {}).get(page, (1.0, 1.0))
        raw = getattr(block, "bbox", None)
        if raw and width and height:
            table_regions.setdefault(page, []).append((raw[0] / width, raw[1] / height, raw[2] / width, raw[3] / height))

    pairs: list[tuple[float, int, int]] = []
    for occurrence_index, occurrence in enumerate(occurrences):
        page = int(occurrence.get("page") or 0)
        source_box = _normalized_bbox(occurrence.get("bbox"))
        if not source_box:
            continue
        for match_index, match in enumerate(matches):
            if int(match.get("page") or 0) != page:
                continue
            detector_box = _normalized_bbox(match.get("bbox"))
            if not detector_box:
                continue
            iou = _normalized_iou(source_box, detector_box)
            source_cover, detector_cover = _intersection_cover(source_box, detector_box)
            if iou < 0.18 and source_cover < 0.62 and detector_cover < 0.62:
                continue
            score = max(iou, source_cover * 0.92, detector_cover * 0.88)
            pairs.append((score, occurrence_index, match_index))

    assigned_occurrences: set[int] = set()
    assigned_matches: set[int] = set()
    assignment: dict[int, int] = {}
    for _score, occurrence_index, match_index in sorted(pairs, reverse=True):
        if occurrence_index in assigned_occurrences or match_index in assigned_matches:
            continue
        assigned_occurrences.add(occurrence_index)
        assigned_matches.add(match_index)
        assignment[occurrence_index] = match_index

    source_value = getattr(parsed, "source_path", None)
    source_path = Path(source_value) if source_value else None
    if not source_path or not source_path.is_file():
        return

    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    fitz_doc = None
    try:
        import fitz  # PyMuPDF; MinerU environments normally already provide it.
        fitz_doc = fitz.open(source_path)
    except Exception:
        fitz_doc = None
    plumber_pdf = pdfplumber.open(source_path)
    try:
        existing_ids = {str(item.get("image_id") or "") for item in matches}
        suppressed = 0
        for occurrence_index, occurrence in enumerate(occurrences):
            page = int(occurrence.get("page") or 0)
            box = _normalized_bbox(occurrence.get("bbox"))
            if not box:
                continue

            width = box[2] - box[0]
            height = box[3] - box[1]
            area = width * height
            if width < 0.018 or height < 0.006 or area < 0.00018:
                continue
            if any(_normalized_iou(box, table) >= 0.55 or _intersection_cover(box, table)[0] >= 0.80 for table in table_regions.get(page, [])):
                # Structured table owns this source occurrence.  Do not create a
                # second standalone image for table decorations/header strips.
                continue

            occurrence_number = int(occurrence.get("occurrence_index") or occurrence_index + 1)
            match_index = assignment.get(occurrence_index)
            if match_index is None and _covered_by_canonical_source(box, page, matches):
                suppressed += 1
                continue
            if match_index is not None:
                image_id = str(matches[match_index].get("image_id") or f"source-p{page}-{occurrence_number:02d}")
            else:
                image_id = f"source-p{page}-{occurrence_number:02d}"
                base_id = image_id
                suffix = 2
                while image_id in existing_ids:
                    image_id = f"{base_id}-{suffix}"
                    suffix += 1
                existing_ids.add(image_id)

            target = _extract_embedded_occurrence(
                source_path,
                occurrence,
                image_dir / image_id,
                fitz_doc=fitz_doc,
                plumber_pdf=plumber_pdf,
            )
            if target is None:
                # Explicitly record that no native embedded image could be
                # materialized.  Never silently fall back to page rendering.
                if match_index is not None:
                    matches[match_index]["source_occurrence_id"] = occurrence.get("source_occurrence_id")
                    matches[match_index]["source_occurrence_status"] = "native_source_unavailable"
                continue

            native_size = occurrence.get("srcsize")
            if match_index is not None:
                match = matches[match_index]
                match["source_occurrence_id"] = occurrence.get("source_occurrence_id")
                match["source_occurrence_status"] = "native_source_extracted"
                match["source_xref"] = occurrence.get("xref")
                match["source_native_size"] = native_size
                original_detector_path = match.get("path")
                if original_detector_path and not match.get("mineru_source_path"):
                    match["mineru_source_path"] = original_detector_path
                match["path"] = str(target.resolve())
                match["source_image_policy"] = "embedded_xobject_native_no_page_render"
                continue

            chunk_id, section = _chunk_meta_for_page(parsed, page)
            matches.append({
                "image_id": image_id,
                "source_occurrence_id": occurrence.get("source_occurrence_id"),
                "source_occurrence_status": "native_source_extracted",
                "source_xref": occurrence.get("xref"),
                "source_native_size": native_size,
                "source_image_policy": "embedded_xobject_native_no_page_render",
                "path": str(target.resolve()),
                "page": page,
                "bbox": list(box),
                "coordinate_space": "normalized_0_1",
                "mineru_type": "pdf_source_image",
                "caption": None,
                "chunk_id": chunk_id,
                "section": section,
                "match_score": 100,
                "match_status": "source_recovered",
                "slot_id": None,
                "slot_status": "not_used",
                "record_status": "candidate",
            })
            enrichments.setdefault(image_id, {
                "image_type": "unknown",
                "caption": "源文档图像",
                "description": "",
                "key_information": [],
                "technical_values": [],
                "needs_review": True,
                "parse_status": "source_recovered_without_vlm",
            })
        if matches:
            matches[0]["suppressed_source_fragments"] = int(matches[0].get("suppressed_source_fragments", 0)) + suppressed
    finally:
        plumber_pdf.close()
        if fitz_doc is not None:
            fitz_doc.close()

def _looks_like_code_or_log_evidence(value: str | None) -> bool:
    """Conservative gate that separates real code/log text from ordinary UI OCR."""
    text = str(value or "").strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    strong_patterns = (
        r"\b(?:CONFIG|TARGET|TEMPLATE|SOURCES|HEADERS|INCLUDEPATH|LIBS|DEFINES|QT)\b",
        r"\b(?:LEVEL|FILE|FUNC|LINK|IntelliSense)\s*[:=]",
        r"\b(?:error|warning|fatal)\b",
        r"(?:^|\s)(?:ping|iperf|sockperf|tcpdump|gdb|java|javac|gcc|g\+\+|zrddsgen(?:\.exe)?)\b",
        r"(?:[A-Za-z]:\\|/home/|/usr/|/etc/|\.cpp\b|\.h\b|\.lib\b|\.dll\b|\.jar\b)",
        r"(?:\+=|-=|:=|==|->|::|#include|\$\(|\$\$quote|0x[0-9A-Fa-f]+)",
    )
    score = sum(bool(re.search(pattern, joined, re.IGNORECASE | re.MULTILINE)) for pattern in strong_patterns)
    if score >= 1:
        return True
    # Dense terminal/log text often contains many punctuation-separated fields.
    punct = sum(joined.count(token) for token in (":", "=", "\\", "/", "(", ")"))
    return len(lines) >= 4 and punct >= 6


def _materialize_code_crops(
    parsed: Any,
    codes: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    enrichments: dict[str, dict[str, Any]],
    image_paths: dict[str, str],
    output_dir: Path,
) -> None:
    """Attach native embedded source images to code occurrences.

    Code images are NEVER generated by rendering/cropping a PDF page.  A code
    block may only reuse a canonical visual that came from a native PDF image
    XObject.  If no such source image exists, the code keeps its text evidence
    but is marked ``no_embedded_source_image`` instead of manufacturing a blurry
    raster crop.
    """
    if not codes:
        return

    visual_regions: list[dict[str, Any]] = []
    for match in matches:
        image_id = str(match.get("image_id") or "")
        if not image_id or _is_table_excluded(match, enrichments.get(image_id, {})):
            continue
        box = _normalized_bbox(match.get("bbox"))
        output_path = image_paths.get(image_id)
        native_ok = str(match.get("source_occurrence_status") or "") == "native_source_extracted"
        if box and output_path and native_ok:
            visual_regions.append({
                "image_id": image_id,
                "page": int(match.get("page") or 0),
                "bbox": box,
                "path": output_path,
                "vlm": enrichments.get(image_id, {}),
                "source_occurrence_id": match.get("source_occurrence_id"),
            })

    used_visual_ids: set[str] = set()
    for code in codes:
        page_number = int(code.get("page") or 0)
        box = _normalized_bbox(code.get("bbox"))
        if not box:
            code["source_image_status"] = "no_code_bbox"
            continue

        owners: list[tuple[float, dict[str, Any]]] = []
        for visual in visual_regions:
            if visual["page"] != page_number or visual["image_id"] in used_visual_ids:
                continue
            overlap = _normalized_iou(box, visual["bbox"])
            inside = _centre_inside_norm(box, visual["bbox"])
            code_cover, visual_cover = _intersection_cover(box, visual["bbox"])
            if overlap >= 0.20 or inside or code_cover >= 0.60 or visual_cover >= 0.60:
                score = max(overlap, code_cover * 0.92, visual_cover * 0.86) + (0.25 if inside else 0.0)
                owners.append((score, visual))

        if not owners:
            code["source_image_path"] = None
            code["source_visual_id"] = None
            code["source_image_status"] = "no_embedded_source_image"
            # Do not call VLM on a page-rendered substitute.  Preserve MinerU as
            # evidence only; layout_model will not pretend a source image exists.
            code["mineru_code_content"] = code.get("code_content")
            code["code_verification_status"] = "native_source_missing"
            continue

        _, owner = max(owners, key=lambda item: item[0])
        owner_vlm = owner.get("vlm") or {}
        mineru_candidate = str(code.get("code_content") or "").strip()
        owner_type = str(owner_vlm.get("image_type") or "unknown")
        # MinerU can label ordinary UI screenshots as code.  Do not let such a
        # record steal the source image from the normal figure pipeline unless
        # there is actual code/command/log syntax evidence.
        if owner_type == "terminal_or_log" or (
            owner_type in {"operation_screenshot", "configuration_screenshot", "architecture_or_flow", "unknown"}
            and not _looks_like_code_or_log_evidence(mineru_candidate)
        ):
            code["record_status"] = "non_code_visual_excluded"
            code["source_image_path"] = None
            code["source_visual_id"] = None
            code["source_image_status"] = "non_code_visual_excluded"
            code["mineru_code_content"] = mineru_candidate or None
            code["code_content"] = ""
            code["code_verification_status"] = "non_code_visual_excluded"
            continue

        used_visual_ids.add(owner["image_id"])
        code["source_image_path"] = owner["path"]
        code["source_visual_id"] = owner["image_id"]
        code["source_occurrence_id"] = owner.get("source_occurrence_id")
        code["source_image_status"] = "reused_native_embedded_occurrence"
        try:
            from app.services.preprocessing.image_vlm import transcribe_code_image
            local_path = output_dir / str(owner["path"])
            existing_verification = owner_vlm.get("code_verification") or {}
            existing_candidate = owner_vlm.get("code_content_candidate")
            if existing_candidate is not None and str(existing_verification.get("status") or "").startswith(("verified_primary", "primary_")):
                code_result = {
                    "code_content": owner_vlm.get("code_content"),
                    "code_content_candidate": existing_candidate,
                    "code_verification": existing_verification,
                    "code_transcription_confidence": owner_vlm.get("code_transcription_confidence"),
                    "code_context_corrections": owner_vlm.get("code_context_corrections") or [],
                    "needs_review": owner_vlm.get("needs_review", False),
                }
            else:
                code_result = transcribe_code_image(
                    local_path,
                    mineru_ocr=str(code.get("code_content") or ""),
                    context=_source_text_context_for_page(parsed, page_number),
                )
                owner_vlm = dict(owner_vlm)
                owner_vlm.update(code_result)
                owner_vlm["image_type"] = "code_or_config"
                owner_vlm["source_image_policy"] = "embedded_xobject_native_no_page_render"
                enrichments[owner["image_id"]] = owner_vlm

            verification = code_result.get("code_verification") or {}
            status = str(verification.get("status") or "primary_transcription_failed")
            candidate = str(code_result.get("code_content_candidate") or "").strip()
            accepted_code = str(code_result.get("code_content") or "").strip()
            code["mineru_code_content"] = code.get("code_content")
            code["code_content_candidate"] = candidate or None
            code["code_verification_status"] = status
            code["code_transcription_confidence"] = code_result.get("code_transcription_confidence")
            code["code_context_corrections"] = code_result.get("code_context_corrections") or []
            code["code_content"] = accepted_code
        except Exception as exc:
            code["mineru_code_content"] = code.get("code_content")
            code["code_content_candidate"] = None
            code["code_content"] = ""
            code["code_verification_status"] = "primary_transcription_failed"
            code["code_transcription_error"] = str(exc)

def build_dataset(parsed: Any, matches: list[dict[str, Any]], enrichments: dict[str, dict[str, Any]], output_dir: Path, *, max_chars: int = 1800, code_matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    code_matches = code_matches or []
    _supplement_pdf_image_occurrences(parsed, matches, enrichments, output_dir)
    _supplement_pdf_vector_figures(parsed, matches, enrichments, output_dir)
    _bind_visual_chunks(parsed, matches, enrichments, code_matches)
    for match in matches:
        if not match.get("path"):
            match["path"] = None
            match["resolution_status"] = "missing_source"
            match["needs_review"] = True
    _enrich_late_source_visuals(parsed, matches, enrichments, code_matches)
    mark_table_header_visuals(parsed, matches, enrichments)
    image_paths: dict[str, str] = {}
    for match in matches:
        image_id = match.get("image_id")
        if not image_id:
            continue
        vlm = enrichments.get(image_id, {})
        if match.get("record_status") != "table_header_excluded":
            match["record_status"] = "table_excluded" if vlm.get("image_type") == "table_image" else (match.get("record_status") or "candidate")
        if _is_table_excluded(match, vlm):
            continue
        source = Path(match.get("path") or "")
        if not source.is_absolute():
            source = Path(match.get("mineru_root", "")) / source
        if source.is_file():
            target = output_dir / "images" / f"{image_id}{source.suffix.lower() or '.jpg'}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            image_paths[image_id] = f"images/{target.name}"
    _materialize_code_crops(parsed, code_matches, matches, enrichments, image_paths, output_dir)
    from app.services.preprocessing.visual_registry import build_visual_registry
    matches, code_matches, registry = build_visual_registry(matches, code_matches, enrichments, image_paths)
    for code in code_matches:
        code["slot_status"] = "canonical_code" if code.get("code_content") else "missing_code_content"

    chunks = []
    for original in parsed.chunks:
        chunk = dict(original)
        records = []
        for match in matches:
            if match.get("chunk_id") != original.get("chunk_id") or not match.get("image_id") or _is_table_excluded(match, enrichments.get(match.get("image_id"), {})):
                continue
            path = image_paths.get(match["image_id"])
            records.append({"image_id": match["image_id"], "path": path, "type": enrichments.get(match["image_id"], {}).get("image_type", "unknown"), "page": match.get("page"), "bbox": match.get("bbox"), "description": enrichments.get(match["image_id"], {}).get("description", ""), "needs_review": bool(enrichments.get(match["image_id"], {}).get("needs_review", False) or match.get("match_status") != "auto_matched"), "binding_status": match.get("binding_status"), "resolution_status": "resolved" if path else "missing_source"})
        for code in code_matches:
            if code.get("chunk_id") == original.get("chunk_id") and code.get("source_image_path"):
                records.append({"image_id": code.get("code_id"), "path": code.get("source_image_path"), "type": "code_original", "page": code.get("page"), "bbox": code.get("bbox"), "needs_review": True, "binding_status": code.get("binding_status"), "resolution_status": "resolved"})
        unique = []
        for record in records:
            old_box = _normalized_bbox(record.get("bbox"))
            duplicate = next((old for old in unique if old.get("path") == record.get("path") and old.get("page") == record.get("page") and old.get("path") and ( _normalized_iou(_normalized_bbox(old.get("bbox")), old_box) >= 0.85 or max(_intersection_cover(_normalized_bbox(old.get("bbox")), old_box)) >= 0.88)), None)
            if duplicate:
                duplicate["roles"] = sorted(set((duplicate.get("roles") or [duplicate.get("type")]) + [record.get("type")]))
                continue
            unique.append(record)
        chunk["images"] = unique
        chunks.append(chunk)

    page_blocks = build_page_blocks(parsed, matches, code_matches or [], enrichments, image_paths)
    markdown = _protect_source_technical_values(render_page_blocks(getattr(parsed, "document", "document.pdf"), page_blocks))
    (output_dir / "enriched.md").write_text(markdown.rstrip() + "\n", encoding="utf-8")
    (output_dir / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "chunks.jsonl").write_text("\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n", encoding="utf-8")
    (output_dir / "layout_blocks.json").write_text(json.dumps([block.to_dict() for block in page_blocks], ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "visual_registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = []
    for match in matches:
        enriched = dict(match)
        enriched["vlm"] = enrichments.get(match["image_id"], {})
        if match.get("record_status") == "table_header_excluded":
            enriched["record_status"] = "table_header_excluded"
        else:
            enriched["record_status"] = "table_excluded" if enriched["vlm"].get("image_type") == "table_image" else (match.get("record_status") or "candidate")
        manifest.append(enriched)
    (output_dir / "image_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    preview = "\n\n".join(f"[{chunk['chunk_id']}] page={chunk['page']} section={chunk['section']}\n{chunk['content']}" for chunk in chunks[:8]) + "\n"
    (output_dir / "preview.txt").write_text(preview, encoding="utf-8")
    return {"chunks": chunks, "manifest": manifest}


def validate_dataset(parsed: Any, matches: list[dict[str, Any]], enrichments: dict[str, dict[str, Any]], output_dir: Path, code_matches: list[dict[str, Any]] | None = None, pdf_image_total: int | None = None) -> dict[str, Any]:
    """Validate canonical output without relying on PDF image-XObject counts."""
    from collections import Counter

    output_dir = Path(output_dir)
    mark_table_header_visuals(parsed, matches, enrichments)
    markdown_path = output_dir / "enriched.md"
    markdown_text = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
    required = ("enriched.md", "chunks.json", "chunks.jsonl", "image_manifest.json", "layout_blocks.json", "preview.txt")

    missing_files = [name for name in required if not (output_dir / name).is_file()]
    image_refs = re.findall(r"!\[[^]]*\]\(images/([^)]*)\)", markdown_text)
    duplicate_image_references = len(image_refs) - len(set(image_refs))

    table_header_excluded = [item.get("image_id") for item in matches if item.get("record_status") == "table_header_excluded"]
    table_excluded = [item.get("image_id") for item in matches if _is_table_excluded(item, enrichments.get(item.get("image_id"), {}))]

    def is_allowed_missing_source(item: dict[str, Any]) -> bool:
        return item.get("path") is None and item.get("resolution_status") == "missing_source" and item.get("needs_review") is True

    def is_ignored_non_knowledge(item: dict[str, Any]) -> bool:
        return item.get("resolution_status") == "ignored_non_knowledge" or item.get("visual_class") in {"structured_table_duplicate", "non_knowledge_visual"}

    active_visuals = [item for item in matches if not _is_table_excluded(item, enrichments.get(item.get("image_id"), {})) and not is_ignored_non_knowledge(item)]
    missing_source_visuals = [item.get("image_id") for item in active_visuals if is_allowed_missing_source(item)]
    unresolved_visuals = [item.get("image_id") for item in active_visuals if is_allowed_missing_source(item) or item.get("binding_status") == "ambiguous"]
    ignored_non_knowledge_visuals = [item.get("image_id") for item in matches if is_ignored_non_knowledge(item)]
    invalid_unresolved = [item.get("image_id") for item in active_visuals if item.get("path") is None and not is_allowed_missing_source(item)]
    expected = [item for item in active_visuals if not is_allowed_missing_source(item)]
    expected_paths = {f"{item.get('image_id')}{Path(item.get('path') or '').suffix.lower() or '.jpg'}": item.get("image_id") for item in expected}
    inserted_ids = [image_id for filename, image_id in expected_paths.items() if filename in set(image_refs)]
    missing_insertions = [item.get("image_id") for item in expected if item.get("image_id") not in inserted_ids and item.get("path")]
    image_accounted_total = len(inserted_ids) + len(table_excluded)
    image_accounting_ok = image_accounted_total == len(matches)

    # Semantic figure coverage is independent of PDF XObject count.  A source
    # figure may be a bitmap, a vector diagram, or one of several figures on a
    # page.  Every real source caption must own one inserted visual occurrence.
    source_figure_captions = _explicit_figure_captions(parsed)
    def figure_caption_key(value: str) -> str:
        normalized = re.sub(r"\s+", "", value)
        match = re.search(r"(\d+[-－]\d+)", normalized)
        return match.group(1).replace("－", "-") if match else normalized

    paired_figure_keys: set[tuple[int, str]] = set()
    inserted_id_set = set(inserted_ids)
    for item in expected:
        image_id = str(item.get("image_id") or "")
        if image_id not in inserted_id_set:
            continue
        caption_text = str((enrichments.get(image_id, {}) or {}).get("caption") or item.get("caption") or "").strip()
        if re.match(r"^(?:图|\u037c)\s*\d+", caption_text):
            paired_figure_keys.add((int(item.get("page") or 0), figure_caption_key(caption_text)))
    paired_figure_pages = {(page, label) for page, label in paired_figure_keys}
    missing_semantic_figures = [
        {"page": int(caption["page"]), "caption": caption["caption"], "figure_number": int(caption["figure_number"])}
        for caption in source_figure_captions
        if (int(caption["page"]), figure_caption_key(str(caption["caption"]))) not in paired_figure_keys
        and (int(caption["page"]) - 1, figure_caption_key(str(caption["caption"]))) not in paired_figure_pages
    ]

    source_headings = [block.text for block in getattr(parsed, "blocks", []) if getattr(block, "heading_level", None)]
    output_heading_matches = list(re.finditer(r"^(#{2,6})\s+(.+?)\s*$", markdown_text, re.MULTILINE))
    output_headings = [match.group(2) for match in output_heading_matches]
    heading_sequence_ok = output_headings == source_headings
    heading_level_jumps = sum(1 for left, right in zip(output_heading_matches, output_heading_matches[1:]) if len(right.group(1)) - len(left.group(1)) > 1)

    source_angles = [token for block in getattr(parsed, "blocks", []) for token in re.findall(r"<[^<>\n]{1,200}>", block.text)]
    # Angle brackets are common in API/XML/C++ syntax. Only unresolved-looking
    # tokens are placeholders; legal technical syntax must not be reported.
    placeholder_words = ("unknown", "unresolved", "placeholder", "待补充", "缺失", "ocr")
    missing_angle_tokens = [
        token for token in source_angles
        if "UNRESOLVED_VISUAL" not in token and not token.startswith("<!--") and token not in markdown_text and any(word in token.lower() for word in placeholder_words)
    ]

    code_matches = code_matches or []
    source_code = [str(item.get("code_content") or "").strip() for item in code_matches if str(item.get("code_content") or "").strip()]
    # MinerU code records often flatten line breaks while Markdown preserves
    # the source block layout. Validate token continuity instead of requiring
    # byte-identical whitespace, while still detecting genuinely missing text.
    normalized_markdown = re.sub(r"\s+", "", markdown_text)
    missing_code_blocks = []
    def code_token_present(token: str) -> bool:
        if token in markdown_text or "�" in token or not token.isascii():
            return True
        # PDF extraction can glue adjacent identifiers when a line break or
        # comment delimiter is lost (for example key + float). Accept the
        # source token when its meaningful parts are present separately.
        if token.isalpha() and len(token) > 6:
            return any(token[:split] in markdown_text and token[split:] in markdown_text for split in range(2, len(token) - 1))
        return False

    for body in source_code:
        normalized_body = re.sub(r"\s+", "", body)
        tokens = [token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}", body) if token]
        if normalized_body not in normalized_markdown and any(not code_token_present(token) for token in tokens):
            missing_code_blocks.append(body)
    fence_markers = re.findall(r"^```", markdown_text, re.MULTILINE)
    unclosed_code_fences = len(fence_markers) % 2

    missing_visual_information = []
    late_source_vlm_failed = []
    for item in expected:
        image_id = str(item.get("image_id") or "")
        value = enrichments.get(image_id, {}) or {}
        image_type = str(value.get("image_type") or "unknown")
        description = str(value.get("description") or "").strip()
        key_information = [str(v).strip() for v in (value.get("key_information") or []) if str(v).strip()]
        code_content = str(value.get("code_content") or "").strip()
        has_output_information = bool(description or key_information or (image_type == "code_or_config" and code_content))
        if not has_output_information and str(value.get("parse_status") or "") not in {"vlm_disabled", "source_recovered_vlm_disabled", "offline_mock"}:
            missing_visual_information.append(image_id)
        if str(value.get("parse_status") or "") in {"source_recovered_without_vlm", "source_recovered_vlm_failed"}:
            late_source_vlm_failed.append(image_id)

    missing_images = []
    for item in expected:
        source = Path(item.get("path") or "")
        if not source.is_absolute():
            output_source = output_dir / source
            source = output_source if output_source.is_file() else (Path(item.get("mineru_root") or "") / source)
        if item.get("path") and not source.is_file():
            missing_images.append(item.get("image_id"))

    knowledge_visuals_without_description = [
        image_id for image_id in missing_visual_information
        if str((enrichments.get(image_id, {}) or {}).get("parse_status") or "") not in {"vlm_disabled", "source_recovered_vlm_disabled", "offline_mock"}
    ]

    chunk_ids = {str(chunk.get("chunk_id")) for chunk in getattr(parsed, "chunks", []) if chunk.get("chunk_id")}
    binding_without_owner = [
        item.get("image_id") for item in expected
        if item.get("binding_status") == "resolved"
        and (not item.get("chunk_id") or str(item.get("chunk_id")) not in chunk_ids)
    ]
    multiple_owners = [
        item.get("image_id") for item in expected
        if len(item.get("owner_chunk_ids") or []) > 1
    ]
    duplicate_physical_occurrences = []
    for index, left in enumerate(expected):
        for right in expected[index + 1:]:
            if left.get("path") != right.get("path") or left.get("page") != right.get("page") or not left.get("path"):
                continue
            if _normalized_iou(_normalized_bbox(left.get("bbox")), _normalized_bbox(right.get("bbox"))) >= 0.85:
                duplicate_physical_occurrences.extend([left.get("image_id"), right.get("image_id")])
    duplicate_physical_occurrences = sorted(set(duplicate_physical_occurrences))

    failures = []
    if missing_files: failures.append("required_files")
    if duplicate_image_references: failures.append("duplicate_image_references")
    if missing_insertions: failures.append("missing_insertions")
    if missing_semantic_figures: failures.append("semantic_figure_coverage")
    if not heading_sequence_ok: failures.append("heading_sequence")
    if heading_level_jumps: failures.append("heading_levels")
    if missing_angle_tokens: failures.append("angle_placeholders")
    if missing_code_blocks: failures.append("code_blocks")
    if unclosed_code_fences: failures.append("unclosed_code_fences")
    if missing_images: failures.append("missing_images")
    if missing_visual_information: failures.append("missing_visual_information")
    if knowledge_visuals_without_description: failures.append("knowledge_visuals_without_description")
    if late_source_vlm_failed: failures.append("late_source_vlm")
    if invalid_unresolved: failures.append("invalid_unresolved_visuals")
    if binding_without_owner: failures.append("binding_without_owner")
    if multiple_owners: failures.append("multiple_owners")
    if duplicate_physical_occurrences: failures.append("duplicate_physical_occurrences")

    qwen_failed = sum(
        str((enrichments.get(item.get("image_id"), {}) or {}).get("parse_status") or "")
        in {"failed", "source_recovered_vlm_failed"}
        for item in expected
    )
    status = "FAIL" if failures or qwen_failed else ("PASS_WITH_UNRESOLVED" if unresolved_visuals else "PASS")
    type_counts = Counter(item.get("image_type", "unknown") for item in enrichments.values())
    report = {
        "status": status,
        "failures": failures,
        "image_total": len(matches),
        "pdf_image_total": pdf_image_total,
        "pdf_image_total_policy": "informational_only",
        "inserted_image_total": len(inserted_ids),
        "inserted_image_ids": inserted_ids,
        "expected_non_table_image_total": len(expected),
        "image_accounted_total": image_accounted_total,
        "image_accounting_ok": image_accounting_ok,
        "missing_insertions": missing_insertions,
        "duplicate_image_references": duplicate_image_references,
        "image_coverage": len(inserted_ids) / len(expected) if expected else 1.0,
        "semantic_figure_total": len(source_figure_captions),
        "semantic_figure_paired_total": len(source_figure_captions) - len(missing_semantic_figures),
        "missing_semantic_figures": missing_semantic_figures,
        "table_excluded_total": len(table_excluded),
        "table_excluded_image_ids": table_excluded,
        "table_header_excluded_total": len(table_header_excluded),
        "table_header_excluded_image_ids": table_header_excluded,
        "heading_sequence_ok": heading_sequence_ok,
        "heading_level_jumps": heading_level_jumps,
        "source_heading_total": len(source_headings),
        "output_heading_total": len(output_headings),
        "missing_angle_tokens": missing_angle_tokens,
        "code_total": len(source_code),
        "missing_code_blocks": len(missing_code_blocks),
        "unclosed_code_fences": unclosed_code_fences,
        "missing_images": missing_images,
        "missing_visual_information": missing_visual_information,
        "knowledge_visuals_without_description": knowledge_visuals_without_description,
        "suppressed_source_fragments": int((matches[0].get("suppressed_source_fragments", 0) if matches else 0)),
        "missing_source_visuals": missing_source_visuals,
        "unresolved_visuals": unresolved_visuals,
        "ignored_non_knowledge_visuals": ignored_non_knowledge_visuals,
        "invalid_unresolved_visuals": invalid_unresolved,
        "knowledge_visual_without_path": invalid_unresolved,
        "processed_visual_count": len(expected),
        "binding_without_owner": binding_without_owner,
        "multiple_owners": multiple_owners,
        "duplicate_physical_occurrences": duplicate_physical_occurrences,
        "late_source_vlm_failed": late_source_vlm_failed,
        "qwen_failed": qwen_failed,
        "image_type_counts": dict(type_counts),
        "slot_total": 0,
        "matched_slot_total": 0,
        "unfilled_slots": [],
        "generated_files": [name for name in (*required, "validation_report.json") if name == "validation_report.json" or (output_dir / name).is_file()],
    }
    (output_dir / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = ["build_dataset", "validate_dataset"]
