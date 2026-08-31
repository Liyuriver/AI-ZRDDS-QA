import json

from app.services.preprocessing.mineru_reader import read_mineru_output


def test_prefers_v2_and_converts_zero_based_page(tmp_path):
    (tmp_path / "doc_content_list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "doc_content_list_v2.json").write_text(json.dumps([
        {"type": "text", "page_idx": 0, "text": "安装配置"},
        {"type": "image", "page_idx": 5, "img_path": "images/a.png", "bbox": [1, 2, 3, 4]},
        {"type": "text", "page_idx": 5, "text": "附加包含目录"},
    ], ensure_ascii=False), encoding="utf-8")
    images = read_mineru_output(tmp_path)
    assert len(images) == 1
    assert images[0].page == 6
    assert images[0].bbox == [1.0, 2.0, 3.0, 4.0]
    assert images[0].nearby_before == ["安装配置"]
    assert images[0].nearby_after == ["附加包含目录"]


def test_preserves_image_records_without_path_and_makes_ids_unique(tmp_path):
    (tmp_path / "doc_content_list_v2.json").write_text(json.dumps([
        {"type": "table", "page_idx": 0, "bbox": [1, 2, 3, 4], "id": "same"},
        {"type": "image", "page_idx": 0, "bbox": [5, 6, 7, 8], "id": "same"},
    ]), encoding="utf-8")

    images = read_mineru_output(tmp_path)

    assert len(images) == 2
    assert images[0].image_id == "same"
    assert images[1].image_id == "same-2"
    assert images[0].image_path == ""
