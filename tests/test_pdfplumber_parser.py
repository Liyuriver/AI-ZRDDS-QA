from app.services.preprocessing.pdfplumber_parser import lines_to_blocks, parse_pdf, split_chunks


def test_baseline_heading_and_chunk_rules_are_preserved():
    blocks = lines_to_blocks([
        ["1. 总则", "说明。", "2. 安装", "2.1. 配置", "配置正文。"],
    ])
    chunks = split_chunks("demo.pdf", blocks, 1800)
    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-0001", "chunk-0002"]
    assert chunks[1]["section"] == "2. 安装 > 2.1. 配置"
    assert "配置正文" in chunks[1]["content"]


def test_parse_pdf_rejects_missing_input(tmp_path):
    try:
        parse_pdf(tmp_path / "missing.pdf")
    except FileNotFoundError as exc:
        assert "PDF not found" in str(exc)
    else:
        raise AssertionError("missing PDF should fail clearly")
