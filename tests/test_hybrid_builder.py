from types import SimpleNamespace

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
