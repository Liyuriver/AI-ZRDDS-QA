"""Materialize already-computed VLM results into existing hybrid artifacts."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path


def atomic_json(path: Path, value) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    manifest = json.loads((root / "image_manifest.json").read_text(encoding="utf-8"))
    by_id = {str(item.get("image_id")): item for item in manifest}

    markdown_path = root / "enriched.md"
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    output = []
    inserted = 0
    image_re = re.compile(r"images/([^/)]+?)(?:\.[A-Za-z0-9]+)?\)?$")
    for line in lines:
        output.append(line)
        match = image_re.search(line) if line.startswith("> ![") else None
        if not match:
            continue
        item = by_id.get(match.group(1))
        vlm = (item or {}).get("vlm") or {}
        description = str(vlm.get("description") or "").strip()
        keys = [str(value).strip() for value in (vlm.get("key_information") or []) if str(value).strip()]
        if vlm.get("parse_status") != "success" or (not description and not keys):
            continue
        output.append("> **图示信息：**")
        if description:
            output.append(f"> - {description}")
        for key in keys:
            output.append(f"> - {key}")
        output.append(">"); inserted += 1
    markdown_path.write_text("\n".join(output) + "\n", encoding="utf-8")

    registry_path = root / "visual_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    updated = 0
    for record in registry:
        item = by_id.get(str(record.get("occurrence_id")))
        vlm = (item or {}).get("vlm") or {}
        if not item or vlm.get("parse_status") != "success":
            continue
        image_type = vlm.get("image_type") or "unknown"
        record["visual_type"] = image_type
        record["roles"] = [image_type]
        record["needs_review"] = bool(vlm.get("needs_review", False))
        record["description"] = vlm.get("description", "")
        record["key_information"] = vlm.get("key_information", [])
        updated += 1
    atomic_json(registry_path, registry)
    print(f"enriched_inserted={inserted} registry_updated={updated}")


if __name__ == "__main__":
    main()
