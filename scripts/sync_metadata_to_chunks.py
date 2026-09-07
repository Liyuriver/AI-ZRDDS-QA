"""Synchronize confirmed document metadata into existing downstream chunks only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.metadata.metadata_service import (  # noqa: E402
    get_metadata_by_source_file,
    sync_document_metadata_to_chunks,
)


def sync_file(path: Path, metadata_path: Path) -> int:
    if path.suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not isinstance(rows, list):
        raise ValueError(f"Expected a list in {path}")
    documents = {row.get("document") for row in rows if isinstance(row, dict) and row.get("document")}
    if len(documents) != 1:
        raise ValueError(f"Expected one source document in {path}, got {documents}")
    metadata = get_metadata_by_source_file(next(iter(documents)), metadata_path)
    updated = sync_document_metadata_to_chunks(rows, metadata)
    if path.suffix == ".json":
        text = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    else:
        text = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in updated) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(updated)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=ROOT / "backend/data/metadata/document_metadata.json")
    parser.add_argument("--hybrid", type=Path, default=ROOT / "backend/data/hybrid")
    args = parser.parse_args()
    paths = sorted(args.hybrid.glob("*/chunks.json")) + sorted(args.hybrid.glob("*/chunks.jsonl"))
    for path in paths:
        print(f"{path}: {sync_file(path, args.metadata)} chunks")


if __name__ == "__main__":
    main()
