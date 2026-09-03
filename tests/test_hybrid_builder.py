from types import SimpleNamespace
import json

from app.services.preprocessing.hybrid_builder import build_dataset, validate_dataset


def test_table_exclusion_is_accounted_separately_from_non_table_insertion(tmp_path):
    image = tmp_path / "source.jpg"
    image.write_bytes(b"not-an-image-but-a-present-source")
    parsed = SimpleNamespace(
        markdown="# doc\n\n### 1. Section\n\n正文。\n",
        chunks=[{"chunk_id": "chunk-0001", "section": "1. Section", "page": 1, "content": "### 1. Section\n\n正文。"}],
    )
    matches = [
        {"image_id": "img-1", "path": str(image), "page": 1, "bbox": [1, 1, 10, 10], "slot_id": None, "chunk_id": "chunk-0001", "section": "1. Section", "match_status": "review", "slot_status": "unmatched_image"},
        {"image_id": "img-table", "path": "", "page": 1, "bbox": [1, 20, 30, 21], "mineru_type": "table", "slot_id": None, "chunk_id": "chunk-0001", "section": "1. Section", "match_status": "review", "slot_status": "table_not_slot"},
    ]
    enrichments = {
        "img-1": {"image_type": "unknown", "parse_status": "success"},
        "img-table": {"image_type": "unknown", "parse_status": "success"},
    }

    build_dataset(parsed, matches, enrichments, tmp_path)
    report = validate_dataset(parsed, matches, enrichments, tmp_path, pdf_image_total=2)

    assert report["table_excluded_image_ids"] == ["img-table"]
    assert report["inserted_image_ids"] == ["img-1"]
    assert report["image_accounted_total"] == 2
    assert report["image_accounting_ok"] is True
    assert report["missing_insertions"] == []


def _validation_files(path):
    for name in ("enriched.md", "chunks.json", "chunks.jsonl", "image_manifest.json", "layout_blocks.json", "preview.txt"):
        target = path / name
        if not target.exists():
            target.write_text("", encoding="utf-8")


def test_validation_accepts_glyph_mapped_figure_caption_and_legal_angle_syntax(tmp_path):
    image = tmp_path / "img-1.jpg"
    image.write_bytes(b"image")
    (tmp_path / "enriched.md").write_text("![ͼ 1-1 demo](images/img-1.jpg)\n\n<安装目录> <item> sequence<int, 4>\n\n```cpp\nstd::vector<int> v;\n```\n", encoding="utf-8")
    _validation_files(tmp_path)
    parsed = SimpleNamespace(
        blocks=[SimpleNamespace(kind="text", text="ͼ 1-1 demo", page=1, bbox=(40, 80, 60, 90), heading_level=None)],
        page_sizes={1: (100, 100)}, chunks=[],
    )
    matches = [{"image_id": "img-1", "path": str(image), "page": 1, "bbox": [0.2, 0.2, 0.8, 0.7], "chunk_id": None, "binding_status": None}]
    enrichments = {"img-1": {"caption": "ͼ 1-1 demo", "description": "diagram", "parse_status": "success"}}
    report = validate_dataset(parsed, matches, enrichments, tmp_path, code_matches=[])
    assert report["missing_semantic_figures"] == []
    assert report["missing_angle_tokens"] == []
    assert report["unclosed_code_fences"] == 0


def test_validation_still_detects_real_angle_placeholder(tmp_path):
    _validation_files(tmp_path)
    (tmp_path / "enriched.md").write_text("正文\n", encoding="utf-8")
    parsed = SimpleNamespace(
        blocks=[SimpleNamespace(kind="text", text="<UNRESOLVED>", page=1, bbox=(0, 0, 10, 10), heading_level=None)],
        page_sizes={1: (100, 100)}, chunks=[],
    )
    report = validate_dataset(parsed, [], {}, tmp_path, code_matches=[])
    assert report["missing_angle_tokens"] == ["<UNRESOLVED>"]
