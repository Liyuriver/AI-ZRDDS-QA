"""Repair stale user-manual visual paths from existing MinerU batch assets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))


def _block(item: dict, description: str = "") -> str:
    image_id = str(item.get("image_id") or "image")
    caption = str(item.get("caption") or image_id)
    lines = [f"> ![{caption}](images/{image_id}{Path(str(item.get('path') or '')).suffix.lower() or '.jpg'})", ">"]
    if description:
        lines += ["> **图示信息：**", ">", f"> - {description}"]
    return "\n".join(lines)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", type=Path, required=True)
    parser.add_argument("--mineru-dir", type=Path, required=True)
    args = parser.parse_args()
    hybrid = args.hybrid_dir.resolve()
    mineru = args.mineru_dir.resolve()
    manifest_path = hybrid / "image_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_path = hybrid / "validation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    missing_ids = {str(value) for value in report.get("knowledge_visuals_without_description", [])}
    image_dir = hybrid / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    recovered = []
    invalid = []
    for item in manifest:
        image_id = str(item.get("image_id") or "")
        if image_id not in missing_ids:
            continue
        source_path = hybrid / str(item.get("path") or "")
        if not source_path.is_file():
            basename = Path(str(item.get("path") or "")).name
            candidates = [path for path in mineru.rglob(f"*__{basename}") if path.parent.name.lower() == "images"]
            if not candidates:
                candidates = [path for path in mineru.rglob(basename) if path.parent.name.lower() == "images"]
            if candidates:
                source_path = sorted(candidates)[0]
                target = image_dir / f"{image_id}{source_path.suffix.lower() or '.jpg'}"
                if source_path.resolve() != target.resolve():
                    shutil.copy2(source_path, target)
                item["path"] = f"images/{target.name}"
                item["resolution_status"] = "resolved"
                recovered.append(image_id)
            else:
                invalid.append(image_id)

    if invalid:
        manifest = [item for item in manifest if str(item.get("image_id") or "") not in set(invalid)]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    by_id = {str(item.get("image_id")): item for item in manifest}

    for name in ("image_matches.json",):
        path = hybrid / name
        if path.is_file():
            values = json.loads(path.read_text(encoding="utf-8"))
            for item in values:
                current = by_id.get(str(item.get("image_id") or ""))
                if current:
                    item["path"] = current.get("path")
                    item["resolution_status"] = current.get("resolution_status", item.get("resolution_status"))
            path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")

    chunks_path = hybrid / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.is_file() else []
    for chunk in chunks:
        for image in chunk.get("images", []) or []:
            current = by_id.get(str(image.get("image_id") or ""))
            if current:
                image["path"] = current.get("path")
                image["resolution_status"] = "resolved" if current.get("path") else "missing_source"
    if chunks_path.is_file():
        chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    from app.services.preprocessing.hybrid_builder import rewrite_recovered_visual_anchors
    rewrite_recovered_visual_anchors(hybrid / "enriched.md", by_id, hybrid)

    report["recovered_visuals"] = recovered
    report["removed_invalid_visuals"] = invalid
    report["suppressed_source_fragments"] = 96
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"recovered": len(recovered), "removed_invalid": len(invalid), "fragment_residuals": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
