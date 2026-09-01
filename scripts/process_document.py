"""The single end-to-end entry point for local hybrid dataset generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.preprocessing.hybrid_builder import build_dataset, validate_dataset
from app.services.preprocessing.image_context_matcher import match_visual_records
from app.services.preprocessing.image_vlm import enrich_image, filter_images, normalize_image_type
from app.services.preprocessing.mineru_reader import MinerUImage, read_mineru_code, read_mineru_output
from app.services.preprocessing.pdfplumber_parser import parse_pdf

import pdfplumber


BACKEND_DATA = REPO_ROOT / "backend" / "data"
SLOT_RE = re.compile(r"<!-- IMAGE_SLOT id=(\S+) page=(\d+) bbox=([\d.,-]+) order=(\d+) -->")


def _load_local_env() -> None:
    """Load simple KEY=value entries without exposing values in logs."""
    env_file = REPO_ROOT / "backend" / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _find_content_list(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.rglob("*_content_list_v2.json"))
    if not candidates:
        candidates = sorted(output_dir.rglob("*_content_list.json"))
    if len(candidates) > 1:
        raise RuntimeError(f"Ambiguous MinerU content lists under {output_dir}: {', '.join(path.name for path in candidates)}")
    return candidates[0] if candidates else None


def _run_mineru(pdf: Path, output_dir: Path) -> tuple[Path, bool]:
    existing = _find_content_list(output_dir)
    if existing:
        return existing, True
    command = os.getenv("MINERU_COMMAND")
    if not command:
        raise RuntimeError("【需要用户配置 MinerU】未配置 MINERU_COMMAND；请配置包含 {pdf} 和 {output} 占位符的 MinerU 命令。")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = command.format(pdf=str(pdf.resolve()), output=str(output_dir.resolve()))
    timeout = int(os.getenv("MINERU_TIMEOUT", "1800"))
    try:
        subprocess.run(rendered, shell=True, check=True, timeout=timeout, cwd=REPO_ROOT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"MinerU 执行超时（{timeout}s）") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"MinerU 执行失败，退出码={exc.returncode}") from exc
    content_list = _find_content_list(output_dir)
    if not content_list:
        raise RuntimeError(f"MinerU completed but no content list was found under {output_dir}")
    return content_list, False


def _write_pdfplumber_intermediate(parsed, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "enriched.md").write_text(parsed.markdown, encoding="utf-8")
    (directory / "chunks.json").write_text(json.dumps(parsed.chunks, ensure_ascii=False, indent=2), encoding="utf-8")


def _recover_missing_mineru_images(pdf: Path, images: list, image_root: Path) -> list:
    """Recover only MinerU records with a page/bbox but no exported file."""
    image_root.mkdir(parents=True, exist_ok=True)
    with pdfplumber.open(pdf) as source_pdf:
        pages = {page.page_number: page for page in source_pdf.pages}
    recovered = []
    for image in images:
        if str(image.raw_type or "").lower() == "table":
            # Tables are represented by pdfplumber正文/table output; never
            # fabricate an image by cropping an unrelated page image.
            recovered.append(image)
            continue
        if not image.image_path:
            recovered.append(image)
            continue
        source = Path(image.image_path) if image.image_path else Path("")
        source = source if source.is_absolute() else image_root.parent / source
        if source.is_file() or not image.bbox or image.page not in pages:
            recovered.append(image)
            continue
        # Do not rasterize a page here. build_dataset() recovers native PDF
        # XObjects and retains this occurrence when MinerU omitted its path.
        recovered.append(image)
    return recovered


def _recover_unrepresented_slots(pdf: Path, parsed: Any, images: list[MinerUImage], image_root: Path, occupied_slot_ids: set[str]) -> list[MinerUImage]:
    """Keep source slots as evidence; never manufacture page-rendered images."""
    return images


def main() -> None:
    _load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--run-tag", default="", help="suffix for a new pdfplumber/hybrid output run; MinerU cache is reused")
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    name = pdf.stem
    # A filename is not an input identity. Reusing mineru/<stem> caused a
    # different PDF with the same name to inherit the previous PDF's images.
    pdf_digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
    run_identity = f"{name}__{pdf_digest}"
    mineru_dir = BACKEND_DATA / "mineru" / run_identity
    output_name = f"{run_identity}__{args.run_tag}" if args.run_tag else run_identity
    pdfplumber_dir = BACKEND_DATA / "pdfplumber" / output_name
    hybrid_dir = BACKEND_DATA / "hybrid" / output_name

    print("[1/7] Parsing PDF with pdfplumber...")
    parsed = parse_pdf(pdf, max_chars=args.max_chars)
    _write_pdfplumber_intermediate(parsed, pdfplumber_dir)
    print(f"OK chunks={len(parsed.chunks)}")

    print("[2/7] Running MinerU...")
    content_list, reused = _run_mineru(pdf, mineru_dir)
    print(f"MINERU_CACHE_HIT: {'YES' if reused else 'NO'}")
    print(f"OK ({'reused' if reused else 'generated'})")

    print("[3/7] Reading MinerU output...")
    mineru_output = content_list.parent
    discovered_images = read_mineru_output(mineru_output)
    discovered_images = _recover_missing_mineru_images(pdf, discovered_images, mineru_output / "images")
    images = filter_images(discovered_images, mineru_output)
    code_records = read_mineru_code(mineru_output)
    print(f"Found {len(discovered_images)} images; retained {len(images)}; code_regions={len(code_records)}")

    print("[4/7] Matching images...")
    matches, code_matches = match_visual_records(parsed.chunks, images, code_records)
    # Only a real MinerU image occupies a visual slot. MinerU code regions
    # describe PDF text and must never suppress the image at the same place.
    occupied_slots = {item["slot_id"] for item in matches if item.get("slot_id")}
    expanded_images = _recover_unrepresented_slots(pdf, parsed, images, mineru_output / "images", occupied_slots)
    if len(expanded_images) != len(images):
        images = expanded_images
        matches, code_matches = match_visual_records(parsed.chunks, images, code_records)
    image_by_id = {image.image_id: image for image in images}
    for item in matches:
        image = image_by_id[item["image_id"]]
        item["mineru_root"] = str(mineru_output)
        item["mineru_type"] = image.raw_type
    for match in matches:
        image = image_by_id[match["image_id"]]
        source = Path(image.image_path) if image.image_path else Path("")
        if not source.is_absolute():
            source = mineru_output / source
        digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else "missing"
        match["image_content_sha256"] = digest if digest != "missing" else None
        match["cache_key"] = hashlib.sha256((digest + "|" + str(match.get("section")) + "|" + match.get("context_before", "") + "|" + match.get("context_after", "") + "|" + os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus") + "|qwen-vl-json-v3").encode("utf-8")).hexdigest()
    print(f"Matched: {sum(item['match_status'] == 'auto_matched' for item in matches)} "
          f"Review: {sum(item['match_status'] == 'review' for item in matches)}")

    print("[5/7] Qwen3-VL...")
    enrichments = {}
    cache = {}
    content_cache = {}
    image_id_cache = {}
    # Qwen results are content/context keyed and may be reused across a new
    # regression directory. Search prior outputs for this PDF stem, while
    # keeping all parsing/MinerU/matching work in the current run fresh.
    manifest_paths = [hybrid_dir / "image_manifest.json"]
    manifest_paths.extend(path / "image_manifest.json" for path in sorted((BACKEND_DATA / "hybrid").glob(f"{name}*")) if path != hybrid_dir)
    for manifest_path in manifest_paths:
        if not manifest_path.is_file():
            continue
        try:
            for item in json.loads(manifest_path.read_text(encoding="utf-8")):
                if item.get("vlm", {}).get("parse_status") == "success" and item.get("cache_key"):
                    cache[item["cache_key"]] = item["vlm"]
                    image_id_cache[str(item.get("image_id") or "")] = item["vlm"]
                    legacy_path = Path(str(item.get("path") or ""))
                    if not legacy_path.is_absolute():
                        legacy_path = manifest_path.parent / legacy_path
                    if legacy_path.is_file():
                        content_cache[hashlib.sha256(legacy_path.read_bytes()).hexdigest()] = item["vlm"]
        except (OSError, json.JSONDecodeError):
            continue
    cache_hits = 0
    cache_misses = 0
    real_api_calls = 0
    api_misses = []
    for index, match in enumerate(matches, start=1):
        image = image_by_id[match["image_id"]]
        source = Path(image.image_path) if image.image_path else Path("")
        if not source.is_absolute():
            source = mineru_output / source
        if not source.is_file():
            enrichments[image.image_id] = {"parse_status": "failed", "needs_review": True, "error": f"image not found: {source}"}
            continue
        cache_key = match["cache_key"]
        content_hash = match.get("image_content_sha256")
        cached_vlm = content_cache.get(content_hash) if content_hash else None
        if cached_vlm is None:
            cached_vlm = cache.get(cache_key)
        # If the PDF identity is unchanged, a stable occurrence id is a safe
        # fallback for trusted historical descriptions produced from a
        # different extractor representation (e.g. native XObject recovery).
        if cached_vlm is None:
            cached_vlm = image_id_cache.get(str(image.image_id))
        if cached_vlm is not None:
            cache_hits += 1
            enrichments[image.image_id] = dict(cached_vlm)
            cached_type = normalize_image_type(enrichments[image.image_id].get("raw_image_type", enrichments[image.image_id].get("image_type")))
            cached_keys = enrichments[image.image_id].get("key_information", [])
            cached_has_code_key = any(re.match(r"^[A-Z][A-Z0-9_]*(?:\s*(?:\+=|-=|:=|\?=|=)\s*)", str(value)) for value in cached_keys)
            if cached_type == "unknown" and (enrichments[image.image_id].get("code_content") or cached_has_code_key):
                cached_type = "code_or_config"
            enrichments[image.image_id]["image_type"] = cached_type
        else:
            cache_misses += 1
            api_misses.append({"image_id": image.image_id, "path": str(source), "hash": content_hash})
            enrichments[image.image_id] = enrich_image(source, document=parsed.document, section=match.get("section"), context_before=match.get("context_before", ""), context_after=match.get("context_after", ""), mineru_ocr=image.raw_ocr_text)
            if enrichments[image.image_id].get("parse_status") not in {"vlm_disabled", "offline_mock"}:
                real_api_calls += 1
        print(f"Processed: {index}/{len(images)}")
    print(f"VLM_CACHE_HIT: {cache_hits}")
    print(f"VLM_CACHE_MISS: {cache_misses}")
    print(f"REAL_API_CALL_COUNT: {real_api_calls}")
    print("API_MISSES:")
    for miss in api_misses:
        print(f"  image_id={miss['image_id']} path={miss['path']} hash={miss['hash']}")

    print("[6/7] Building hybrid document...")
    build_dataset(parsed, matches, enrichments, hybrid_dir, max_chars=args.max_chars, code_matches=code_matches)
    (hybrid_dir / "image_matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    (hybrid_dir / "code_matches.json").write_text(json.dumps(code_matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK")

    print("[7/7] Validation...")
    report = validate_dataset(parsed, matches, enrichments, hybrid_dir, code_matches=code_matches)
    registry_path = hybrid_dir / "visual_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else []
    owner_mismatch = len(report.get("binding_without_owner", [])) + len(report.get("multiple_owners", []))
    markdown_chunk_mismatch = int("markdown_chunk_mismatch" in report.get("failures", []))
    print(f"Validation: {report['status']}")
    print(f"hard_failures: {len(report.get('failures', [])) + int(report.get('qwen_failed', 0) > 0)}")
    print(f"missing_knowledge_visuals: {len(report.get('missing_insertions', []))}")
    print(f"missing_source_visuals: {len(report.get('missing_source_visuals', []))}")
    duplicate_occurrences = report.get("duplicate_physical_occurrences", [])
    duplicate_references = report.get("duplicate_image_references", 0)
    duplicate_count = (len(duplicate_occurrences) if isinstance(duplicate_occurrences, list) else int(duplicate_occurrences or 0)) + (len(duplicate_references) if isinstance(duplicate_references, list) else int(duplicate_references or 0))
    print(f"duplicate_visuals: {duplicate_count}")
    print(f"owner_mismatch: {owner_mismatch}")
    print(f"markdown_chunk_mismatch: {markdown_chunk_mismatch}")
    print(f"unclosed_code_fences: {report.get('unclosed_code_fences', 0)}")
    print(f"recovered_visuals: {sum(str(item.get('resolution_status', '')).startswith('recovered_') for item in registry)}")
    if report.get("failures"):
        print("Validation failures: " + ", ".join(report["failures"]))
    print(f"Output: {hybrid_dir}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
