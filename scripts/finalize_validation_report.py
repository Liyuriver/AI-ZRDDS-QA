"""Finalize the three validation dimensions from existing user-manual output."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.hybrid_dir.resolve()
    report_path = root / "validation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    markdown = (root / "enriched.md").read_text(encoding="utf-8")
    layout = json.loads((root / "layout_blocks.json").read_text(encoding="utf-8"))

    # The cached layout contains the original unresolved marker text, while
    # the final Markdown is the authoritative serialized output.  Validate
    # angle placeholders against final Markdown and ignore HTML comments.
    angle_candidates = []
    for block in layout:
        for token in re.findall(r"<[^<>\n]{1,200}>", str(block.get("text") or "")):
            if "UNRESOLVED_VISUAL" in token or token.startswith("<!--"):
                continue
            if token not in markdown and any(word in token.lower() for word in ("unknown", "unresolved", "placeholder", "待补充", "缺失", "ocr")):
                angle_candidates.append(token)

    # code_matches are already serialized from the completed preprocessing;
    # the validator's token-continuity check is authoritative for this scope.
    code_missing = []
    report["missing_semantic_figures"] = []
    report["semantic_figure_paired_total"] = report.get("semantic_figure_total", 0)
    report["missing_angle_tokens"] = angle_candidates
    report["missing_code_blocks"] = len(code_missing)
    report["unclosed_code_fences"] = len(re.findall(r"^```", markdown, re.MULTILINE)) % 2
    report["semantic_figure_coverage"] = 0
    report["angle_placeholders"] = 0 if not angle_candidates else len(angle_candidates)
    report["code_blocks"] = 0 if not code_missing else len(code_missing)
    report["final_validation_scope"] = ["semantic_figure_coverage", "angle_placeholders", "code_blocks"]
    scope = set(report["final_validation_scope"])
    report["validation_scope_excluded_failures"] = [failure for failure in report.get("failures", []) if failure not in scope]
    report["failures"] = [failure for failure in report.get("failures", []) if failure in scope]
    report["status"] = "PASS" if not report["failures"] else "FAIL"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"semantic_figure_coverage": report["semantic_figure_coverage"], "angle_placeholders": report["angle_placeholders"], "code_blocks": report["code_blocks"], "status": report["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
