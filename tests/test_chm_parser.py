from pathlib import Path

from app.services.preprocessing import chm_parser


def test_parse_chm_preserves_structure_and_common_assets(tmp_path, monkeypatch):
    chm = tmp_path / "manual.chm"
    chm.write_bytes(b"placeholder")
    html = tmp_path / "source" / "guide.html"
    image = tmp_path / "source" / "img" / "diagram.png"
    html.parent.mkdir(parents=True)
    image.parent.mkdir()
    image.write_bytes(b"png")
    html.write_text("""<html><head><title>Guide</title></head><body>
      <h1>Overview</h1><p>See <a href='next.html'>next</a>.</p>
      <pre>  if (x) {\n    return 1;\n  }</pre>
      <table><tr><th>Name</th><th>Value</th></tr><tr><td>A|B</td><td>1</td></tr></table>
      <p><img src='img/diagram.png' alt='diagram'></p>
    </body></html>""", encoding="utf-8")

    def fake_decompile(_path: Path, root: Path):
        target = root / "guide.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(html.read_bytes())
        target_image = root / "img" / "diagram.png"
        target_image.parent.mkdir(exist_ok=True)
        target_image.write_bytes(image.read_bytes())

    monkeypatch.setattr(chm_parser, "_decompile", fake_decompile)
    parsed = chm_parser.parse_chm(chm, tmp_path / "out", metadata={"language": "en"})

    assert "# Overview" in parsed.markdown
    assert "```en\n  if (x) {" in parsed.markdown
    assert "| Name | Value |" in parsed.markdown
    assert "A\\|B" in parsed.markdown
    assert "assets/images/" in parsed.markdown
    assert (tmp_path / "out" / "assets" / "images").iterdir().__next__().is_file()
    assert parsed.chunks[0]["source_file"] == "manual.chm"
    assert parsed.chunks[0]["source_page"] == "guide.html"
    assert parsed.chunks[0]["language"] == "en"


def test_pdf_parser_public_api_remains_available():
    from app.services.preprocessing import parse_pdf

    assert callable(parse_pdf)
