"""Rerun only missing VLM descriptions for an existing hybrid output."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))
from app.services.preprocessing.image_vlm import enrich_image  # noqa: E402


def _load_env() -> None:
    env_file = BACKEND / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _atomic_json(path: Path, value) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1, help="maximum number of missing descriptions to call")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    _load_env()
    root = args.output.resolve()
    manifest_path = root / "image_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = []
    for item in manifest:
        status = str((item.get("vlm") or {}).get("parse_status") or "")
        source = root / str(item.get("path") or "")
        if status == "success" or not source.is_file():
            continue
        candidates.append((item, source))
    print(f"candidates={len(candidates)} selected={min(max(args.limit, 0), len(candidates))}")
    if args.dry_run or args.limit <= 0:
        return 0
    os.environ["ENABLE_VLM"] = "true"
    os.environ["VLM_TIMEOUT"] = str(args.timeout)
    os.environ["VLM_RETRIES"] = str(args.retries)
    selected = candidates[:args.limit]

    def run_one(pair):
        item, source = pair
        try:
            result = enrich_image(source, document=str(item.get("document") or "formal-22-04-01.pdf"),
                                  section=item.get("section"), context_before="", context_after="", mineru_ocr=None,
                                  timeout=args.timeout, retries=args.retries)
        except Exception as exc:
            result = {"parse_status": "failed", "needs_review": True, "error": f"{type(exc).__name__}: {exc}"}
        return item, result

    processed = success = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(run_one, pair): pair[0].get("image_id") for pair in selected}
        for index, future in enumerate(as_completed(futures), 1):
            item, result = future.result()
            processed += 1
            print(f"VLM {processed}/{len(selected)}: {item.get('image_id')}")
            old_vlm = dict(item.get("vlm") or {})
            old_caption = old_vlm.get("caption")
            old_caption_source = old_vlm.get("caption_source")
            old_vlm.update(result)
            if old_caption and not old_vlm.get("caption"):
                old_vlm["caption"] = old_caption
            if old_caption_source and not old_vlm.get("caption_source"):
                old_vlm["caption_source"] = old_caption_source
            item["vlm"] = old_vlm
            if result.get("parse_status") == "success":
                success += 1
            else:
                failed += 1
    _atomic_json(manifest_path, manifest)
    by_id = {str(item.get("image_id")): item for item in manifest}
    chunks_path = root / "chunks.json"
    if chunks_path.is_file():
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        for chunk in chunks:
            for image in chunk.get("images") or []:
                item = by_id.get(str(image.get("image_id")))
                if not item:
                    continue
                vlm = item.get("vlm") or {}
                image["type"] = vlm.get("image_type", image.get("type", "unknown"))
                image["description"] = vlm.get("description", image.get("description", ""))
                image["needs_review"] = bool(vlm.get("needs_review", image.get("needs_review", False)))
        _atomic_json(chunks_path, chunks)
        jsonl_path = root / "chunks.jsonl"
        jsonl_path.write_text("\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n", encoding="utf-8")
    print(f"processed={processed} success={success} failed={failed}")
    print("Updated image_manifest.json and chunk image metadata; enriched.md/visual registry are unchanged.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
