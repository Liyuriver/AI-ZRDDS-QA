"""Finish existing visual artifacts without rerunning parsing, MinerU, or VLM."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.preprocessing.hybrid_builder import rewrite_recovered_visual_anchors


FIG = re.compile(r"(?:图|ͼ)\s*(\d+\s*[-－]\s*\d+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.hybrid_dir.resolve()
    manifest_path = root / "image_manifest.json"
    matches_path = root / "image_matches.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    by_id = {str(x.get("image_id")): x for x in manifest}
    match_by_id = {str(x.get("image_id")): x for x in matches}

    excluded: set[str] = set()
    for item in manifest:
        vlm = item.get("vlm") or {}
        if vlm.get("image_type") == "table_image" and item.get("mineru_type") == "table" and not item.get("chunk_id"):
            image_id = str(item.get("image_id") or "")
            if image_id:
                excluded.add(image_id)
                item["visual_class"] = "non_knowledge_visual"
                item["binding_status"] = "excluded"
                item["binding_reason"] = "table_image_without_knowledge_owner"
                item["resolution_status"] = "resolved"
                item["exclusion_reason"] = "table_image_no_independent_knowledge_value"
                match = match_by_id.get(image_id)
                if match:
                    match.update(visual_class="non_knowledge_visual", binding_status="excluded", binding_reason=item["binding_reason"], resolution_status="resolved")

    # Split a multi-caption visual only when the page already has ordered
    # neighboring figure records: the latter label belongs to the latter
    # record.  This is based on caption structure/order, never on IDs/pages.
    caption_changes: dict[str, str] = {}
    for item in manifest:
        current = str(item.get("caption") or "").strip()
        vlm_caption = str((item.get("vlm") or {}).get("caption") or "").strip()
        if not current and len(FIG.findall(vlm_caption)) == 1:
            caption_changes[str(item.get("image_id") or "")] = vlm_caption
    pages: dict[int, list[dict]] = {}
    for item in manifest:
        if item.get("image_id") in excluded:
            continue
        page = int(item.get("page") or 0)
        if page:
            pages.setdefault(page, []).append(item)
    for page_items in pages.values():
        ordered = sorted(page_items, key=lambda x: (float((x.get("bbox") or [0, 0])[1]), str(x.get("image_id"))))
        for index, item in enumerate(ordered):
            labels = FIG.findall(str(item.get("caption") or (item.get("vlm") or {}).get("caption") or ""))
            if len(labels) < 2 or index == 0:
                continue
            previous = ordered[index - 1]
            previous_labels = FIG.findall(str(previous.get("caption") or (previous.get("vlm") or {}).get("caption") or ""))
            if previous_labels and previous_labels[-1] == labels[0]:
                if not previous.get("caption") and len(previous_labels) == 1:
                    caption_changes[str(previous["image_id"])] = f"ͼ {previous_labels[0].replace(' ', '')}"
                caption_changes[str(item["image_id"])] = f"图 {labels[1].replace(' ', '')}"

    for image_id, caption in caption_changes.items():
        item = by_id[image_id]
        item["caption"] = caption
        if item.get("vlm") is not None:
            item["vlm"]["caption"] = caption
        match = match_by_id.get(image_id)
        if match:
            match["caption"] = caption

    # Remove only placeholders whose existing visual is explicitly excluded.
    markdown_path = root / "enriched.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    for image_id in excluded:
        markdown = re.sub(rf"^\s*<!--\s*UNRESOLVED_VISUAL\s+image_id={re.escape(image_id)}[^\n]*\n?", "", markdown, flags=re.MULTILINE)
    for image_id, caption in caption_changes.items():
        markdown = re.sub(rf"(> !\[)[^]]*(\]\(images/{re.escape(image_id)}\.[^)]+\))", rf"\g<1>{caption}\g<2>", markdown)
    markdown_path.write_text(markdown, encoding="utf-8")

    # Replace any other resolved anchors and remove duplicate tail blocks.
    anchor_stats = rewrite_recovered_visual_anchors(markdown_path, by_id, root)

    chunks_path = root / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    for chunk in chunks:
        chunk["images"] = [image for image in (chunk.get("images") or []) if image.get("image_id") not in excluded]
        for image in chunk["images"]:
            if image.get("image_id") in caption_changes:
                image["caption"] = caption_changes[image["image_id"]]
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    registry_path = root / "visual_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for item in registry:
        image_id = str(item.get("occurrence_id") or "")
        if image_id in excluded:
            item.update(visual_class="non_knowledge_visual", binding_status="excluded", binding_reason="table_image_without_knowledge_owner", resolution_status="resolved")
        if image_id in caption_changes:
            item["caption"] = caption_changes[image_id]
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    matches_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = {
        "excluded_non_knowledge_visuals": len(excluded),
        "caption_changes": caption_changes,
        **anchor_stats,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
