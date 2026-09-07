"""Recover composite PDF figures by rendering the original page region.

This is an incremental repair tool.  It never invokes MinerU and only calls
the VLM for canonical images whose bytes changed during this repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image, ImageStat


FIGURE_RE = re.compile(r"(?:图|ͼ)?\s*(\d+\s*[-－]\s*\d+)")


def _box(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x0, y0, x1, y1 = map(float, value[:4])
    except (TypeError, ValueError):
        return None
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _render_crop(pdf: Path, page_number: int, crop: tuple[float, float, float, float], page_size: tuple[float, float], target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="zrdds_composite_") as temp:
        prefix = Path(temp) / "page"
        subprocess.run(["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "220", "-png", "-singlefile", str(pdf), str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        rendered = Image.open(str(prefix) + ".png").convert("RGB")
        sx, sy = rendered.width / page_size[0], rendered.height / page_size[1]
        x0, y0, x1, y1 = crop
        pixels = (max(0, int(x0 * sx)), max(0, int(y0 * sy)), min(rendered.width, int(x1 * sx)), min(rendered.height, int(y1 * sy)))
        if pixels[2] <= pixels[0] or pixels[3] <= pixels[1]:
            raise ValueError("empty page crop")
        target.parent.mkdir(parents=True, exist_ok=True)
        rendered.crop(pixels).save(target, format="PNG")


def _description_block(item: dict[str, Any]) -> list[str]:
    path = str(item.get("path") or "").replace("\\", "/")
    rel = path[path.find("images/"):] if "images/" in path else path
    caption = str(item.get("caption") or "").strip()
    vlm = item.get("vlm") or {}
    description = str(vlm.get("description") or "").strip()
    lines = [f"> ![{caption or item.get('image_id', '')}]({rel})"]
    if caption:
        lines.append(f"> **{caption}**")
    if description:
        lines.append(f"> **图示信息：** {description}")
    return lines


def _sync_markdown(path: Path, changed: dict[str, dict[str, Any]]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for image_id, item in changed.items():
        marker = f"images/{image_id}."
        start = next((i for i, line in enumerate(lines) if marker in line), None)
        if start is None:
            continue
        end = start + 1
        while end < len(lines) and (lines[end].startswith(">") or not lines[end].strip()):
            end += 1
        lines[start:end] = _description_block(item)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--hybrid-dir", required=True, type=Path)
    parser.add_argument("--vlm-timeout", type=float, default=90.0)
    args = parser.parse_args()

    root = args.hybrid_dir
    manifest_path, matches_path = root / "image_manifest.json", root / "image_matches.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    match_by_id = {str(x.get("image_id")): x for x in matches}
    image_dir = root / "images"
    stats = {"composite_figure_candidates": 0, "fragment_canonical_detected": 0, "page_crop_recovered": 0, "canonical_content_replaced": 0, "description_invalidated": 0, "vlm_calls": 0}
    changed: dict[str, dict[str, Any]] = {}

    with pdfplumber.open(args.pdf) as pdf:
        for item in manifest:
            caption = str(item.get("caption") or "")
            number = FIGURE_RE.search(caption)
            page_number = int(item.get("page") or 0)
            canonical = _box(item.get("bbox"))
            if not number or not canonical or page_number < 1 or page_number > len(pdf.pages):
                continue
            page = pdf.pages[page_number - 1]
            pw, ph = float(page.width), float(page.height)
            canonical_pt = (canonical[0] * pw, canonical[1] * ph, canonical[2] * pw, canonical[3] * ph)
            objects = []
            for source in page.images:
                source_box = _box([source.get("x0"), source.get("top"), source.get("x1"), source.get("bottom")])
                if source_box:
                    objects.append(source_box)
            nearby = [box for box in objects if _overlap(box, canonical_pt) > 0 or (box[1] <= canonical_pt[3] + 42 and box[3] >= canonical_pt[1] - 42)]
            if len(nearby) < 3:
                continue
            old_path = root / str(item.get("path") or "")
            if not old_path.is_file():
                continue
            with Image.open(old_path) as old_image:
                mean = sum(ImageStat.Stat(old_image.convert("RGB")).mean) / 3.0
                native = item.get("source_native_size") or match_by_id.get(str(item.get("image_id")), {}).get("source_native_size") or []
            # A canonical backed by a very small native object, while several
            # other objects occupy the same captioned region, is a fragment.
            if not isinstance(native, (list, tuple)) or len(native) < 2:
                continue
            if int(native[0]) * int(native[1]) > 30000 and mean > 80:
                continue
            stats["composite_figure_candidates"] += 1
            stats["fragment_canonical_detected"] += 1
            region = _union(nearby)
            pad_x, pad_y = max(10.0, pw * 0.018), max(8.0, ph * 0.012)
            crop = (max(0, region[0] - pad_x), max(0, region[1] - pad_y), min(pw, region[2] + pad_x), min(ph, region[3] + pad_y))
            image_id = str(item.get("image_id"))
            target = image_dir / f"{image_id}.png"
            _render_crop(args.pdf, page_number, crop, (pw, ph), target)
            stats["page_crop_recovered"] += 1
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            old_digest = str(item.get("content_sha256") or match_by_id.get(image_id, {}).get("image_content_sha256") or "")
            if digest == old_digest:
                continue
            stats["canonical_content_replaced"] += 1
            if item.get("vlm", {}).get("description"):
                stats["description_invalidated"] += 1
            item["path"] = f"images/{image_id}.png"
            item["bbox"] = [crop[0] / pw, crop[1] / ph, crop[2] / pw, crop[3] / ph]
            item["content_sha256"] = digest
            item["vlm"] = {**(item.get("vlm") or {}), "description": "", "key_information": [], "technical_values": [], "parse_status": "content_changed_vlm_pending"}
            item["source_image_policy"] = "pdf_page_crop_composite_figure"
            match = match_by_id.get(image_id)
            if match:
                match["path"] = f"images/{image_id}.png"
                match["bbox"] = item["bbox"]
                match["image_content_sha256"] = digest
                match["source_image_policy"] = "pdf_page_crop_composite_figure"
            changed[image_id] = item

    if changed:
        # Deliberately import only after local files are changed: one VLM call
        # is made per changed canonical image, never for the whole document.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.services.preprocessing.image_vlm import enrich_image
        for image_id, item in changed.items():
            result = enrich_image(image_dir / f"{image_id}.png", document=args.pdf.name, section=item.get("section"), context_before="", context_after="", mineru_ocr=None, timeout=args.vlm_timeout, retries=2)
            item["vlm"] = result
            item["vlm"]["content_sha256"] = item["content_sha256"]
            item["vlm"]["parse_status"] = "composite_page_crop_vlm"
            stats["vlm_calls"] += 1
            match = match_by_id.get(image_id)
            if match:
                match["image_content_sha256"] = item["content_sha256"]
                match["description"] = result.get("description", "")

        for chunk in json.loads((root / "chunks.json").read_text(encoding="utf-8")):
            for visual in chunk.get("images") or []:
                if visual.get("image_id") in changed:
                    item = changed[visual["image_id"]]
                    visual["path"] = item["path"]
                    visual["bbox"] = item["bbox"]
                    visual["description"] = item["vlm"].get("description", "")
        chunks = json.loads((root / "chunks.json").read_text(encoding="utf-8"))
        for chunk in chunks:
            for visual in chunk.get("images") or []:
                if visual.get("image_id") in changed:
                    item = changed[visual["image_id"]]
                    visual.update(path=item["path"], bbox=item["bbox"], description=item["vlm"].get("description", ""))
        (root / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        registry_path = root / "visual_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for entry in registry:
            if entry.get("occurrence_id") in changed:
                item = changed[entry["occurrence_id"]]
                entry.update(path=item["path"], bbox=item["bbox"], description=item["vlm"].get("description", ""))
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        _sync_markdown(root / "enriched.md", changed)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    matches_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
