"""Resume VLM descriptions for one existing hybrid output without reprocessing its PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.preprocessing.image_vlm import enrich_image


def _valid_description(value: object) -> bool:
    return bool(str(value or "").strip())


def _load_env() -> None:
    env_file = Path(__file__).resolve().parents[1] / "backend" / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _write_markdown(path: Path, descriptions: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    for index, line in enumerate(lines):
        output.append(line)
        if not line.startswith("> ![") or "images/" not in line:
            continue
        image_name = line.rsplit("images/", 1)[1].split(")", 1)[0]
        image_id = Path(image_name).stem
        description = descriptions.get(image_id)
        if not description or any("**图示信息：**" in existing for existing in lines[index + 1:index + 5]):
            continue
        output.extend([">", "> **图示信息：**", ">", f"> - {description}"])
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=float(os.getenv("VLM_REPAIR_TIMEOUT", "90")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("VLM_REPAIR_RETRIES", "2")))
    args = parser.parse_args()
    root = args.hybrid_dir.resolve()
    manifest_path = root / "image_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = []
    for item in manifest:
        value = item.get("vlm") or {}
        image_path = root / str(item.get("path") or "")
        if item.get("visual_class") != "knowledge_visual" or not image_path.is_file() or _valid_description(value.get("description")):
            continue
        targets.append((item, image_path))

    counts = {"hit": 0, "miss": 0, "api": 0, "retry": 0, "timeout": 0}
    descriptions: dict[str, str] = {}
    for index, (item, image_path) in enumerate(targets, 1):
        image_id = str(item.get("image_id") or "")
        value = item.setdefault("vlm", {})
        content_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if _valid_description(value.get("description")):
            counts["hit"] += 1
            print(f"VLM [{index}/{len(targets)}] {image_id} HIT")
            continue
        counts["miss"] += 1
        result = None
        for attempt in range(args.retries + 1):
            if attempt:
                counts["retry"] += 1
                time.sleep(min(2 ** (attempt - 1), 8))
                print(f"VLM [{index}/{len(targets)}] {image_id} RETRY {attempt}/{args.retries}")
            started = time.perf_counter()
            result = enrich_image(image_path, document="ZRDDS用户手册.pdf", section=item.get("section"), context_before="", context_after="", mineru_ocr=None, timeout=args.timeout, retries=0)
            if result.get("parse_status") == "success":
                counts["api"] += 1
                value.update(result)
                value["content_sha256"] = content_hash
                value["document_identity"] = root.name
                description = str(value.get("description") or "").strip()
                if description:
                    descriptions[image_id] = description
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"VLM [{index}/{len(targets)}] {image_id} API PASS {time.perf_counter() - started:.3f}s")
                break
            error = str(result.get("error") or "")
            if "timeout" in error.lower() or "timed out" in error.lower():
                counts["timeout"] += 1
        else:
            value["parse_status"] = "failed"
            value["error"] = (result or {}).get("error", "VLM description failed")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"VLM [{index}/{len(targets)}] {image_id} FAIL: {value['error']}")

    for item in manifest:
        value = item.get("vlm") or {}
        if _valid_description(value.get("description")):
            descriptions.setdefault(str(item.get("image_id") or ""), str(value["description"]).strip())
    from app.services.preprocessing.hybrid_builder import rewrite_recovered_visual_anchors
    rewrite_recovered_visual_anchors(root / "enriched.md", {str(item.get("image_id")): item for item in manifest}, root)

    chunks_path = root / "chunks.json"
    if chunks_path.is_file():
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        by_id = {str(item.get("image_id")): str((item.get("vlm") or {}).get("description") or "") for item in manifest}
        for chunk in chunks:
            for image in chunk.get("images", []) or []:
                image["description"] = by_id.get(str(image.get("image_id")), image.get("description", ""))
        chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    registry_path = root / "visual_registry.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        by_id = {str(item.get("image_id")): str((item.get("vlm") or {}).get("description") or "") for item in manifest}
        for item in registry:
            item["description"] = by_id.get(str(item.get("occurrence_id") or ""), item.get("description", ""))
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"targets": len(targets), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
