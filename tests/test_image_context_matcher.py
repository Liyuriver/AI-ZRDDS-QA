from app.services.preprocessing.image_context_matcher import match_images
from app.services.preprocessing.image_context_matcher import match_visual_records
from app.services.preprocessing.mineru_reader import MinerUImage
from types import SimpleNamespace
from app.services.preprocessing.image_context_matcher import resolve_visual_chunk


def test_image_matches_same_section_using_page_and_text_anchor():
    chunks = [
        {"chunk_id": "chunk-0001", "section": "1. 概述", "page": 2, "content": "产品介绍。"},
        {"chunk_id": "chunk-0002", "section": "2.5.2 配置包含文件目录", "page": 6, "content": "### 2.5.2 配置包含文件目录\n配置附加包含目录。"},
    ]
    image = MinerUImage(
        image_id="img-p6-01", image_path="images/a.png", page=6, bbox=None,
        raw_type="image", caption="配置包含文件目录", nearby_before=["配置"],
        nearby_after=["附加包含目录"],
    )
    result = match_images(chunks, [image])[0]
    assert result["chunk_id"] == "chunk-0002"
    assert result["section"] == "2.5.2 配置包含文件目录"
    assert result["match_status"] in {"auto_matched", "review"}


def test_table_record_does_not_consume_the_first_visual_slot():
    chunks = [{
        "chunk_id": "chunk-0001", "section": "1. Section", "page": 1,
        "content": "<!-- IMAGE_SLOT id=slot-p1-01 page=1 bbox=1,1,10,10 order=1 -->\n正文。",
    }]
    table = MinerUImage("table", "", 1, [1, 1, 10, 2], "table", None)
    image = MinerUImage("image", "images/a.png", 1, [1, 3, 10, 10], "image", None)

    matches, _ = match_visual_records(chunks, [table, image], [])

    by_id = {item["image_id"]: item for item in matches}
    assert by_id["table"]["slot_status"] == "table_not_slot"
    assert by_id["table"]["slot_id"] is None
    assert by_id["image"]["slot_id"] == "slot-p1-01"


def test_unmatched_image_is_unresolved_when_no_source_slot_exists():
    chunks = [
        {"chunk_id": "chunk-1", "section": "1. Intro", "page": 7, "content": "intro"},
        {"chunk_id": "chunk-2", "section": "2. Next", "page": 9, "content": "next"},
    ]
    image = MinerUImage("image", "images/a.png", 8, [1, 1, 10, 10], "image", None)

    result = match_visual_records(chunks, [image], [])[0][0]

    assert result["slot_id"] is None
    assert result["chunk_id"] is None


def test_top_of_page_visual_inherits_previous_section_before_new_heading():
    blocks = [
        SimpleNamespace(page=1, order=1, bbox=(0, 0, 100, 20), heading_level=2, text="A"),
        SimpleNamespace(page=1, order=2, bbox=(0, 25, 100, 50), heading_level=None, text="text A"),
        SimpleNamespace(page=2, order=3, bbox=(0, 20, 100, 45), heading_level=2, text="B"),
    ]
    chunks = [
        {"chunk_id": "chunk-a", "section": "A", "page": 1, "source_pages": [1], "source_block_start": 1, "source_block_end": 2},
        {"chunk_id": "chunk-b", "section": "B", "page": 2, "source_pages": [2], "source_block_start": 3, "source_block_end": 3},
    ]
    result = resolve_visual_chunk({"page": 2, "bbox": [0.1, 0.01, 0.9, 0.12]}, chunks, blocks, {2: (100, 100)})
    assert result["chunk_id"] == "chunk-a"


def test_visual_after_page_heading_belongs_to_new_section():
    blocks = [SimpleNamespace(page=2, order=3, bbox=(0, 20, 100, 45), heading_level=2, text="B")]
    chunks = [{"chunk_id": "chunk-b", "section": "B", "page": 2, "source_pages": [2], "source_block_ids": [3]}]
    result = resolve_visual_chunk({"page": 2, "bbox": [0.1, 0.5, 0.9, 0.8]}, chunks, blocks, {2: (100, 100)})
    assert result["chunk_id"] == "chunk-b"
