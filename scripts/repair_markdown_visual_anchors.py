"""Repair recovered visual placeholders in an existing hybrid Markdown file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.preprocessing.hybrid_builder import rewrite_recovered_visual_anchors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.hybrid_dir.resolve()
    manifest = json.loads((root / "image_manifest.json").read_text(encoding="utf-8"))
    visuals = {str(item.get("image_id") or ""): item for item in manifest}
    stats = rewrite_recovered_visual_anchors(root / "enriched.md", visuals, root)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
