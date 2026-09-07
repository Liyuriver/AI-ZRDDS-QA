"""CHM front-end: decompile with hh.exe and serialize HTML to the PDF parser's blocks."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import logging
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.services.preprocessing.pdfplumber_parser import Block, ParsedDocument, split_chunks

LOGGER = logging.getLogger(__name__)
HTML_ENCODINGS = ("utf-8", "gb18030", "gbk", "gb2312", "windows-1252", "latin-1")


def _decode_html(raw: bytes, path: Path, stats: dict) -> str:
    """Decode strictly; HTML declarations win, then charset-normalizer/candidates."""
    head = raw[:8192].decode("latin-1")
    declared = re.search(r"<meta[^>]+charset\s*=\s*[\"']?\s*([\w.-]+)", head, re.I)
    if not declared:
        declared = re.search(r"<meta[^>]+content\s*=\s*[\"'][^\"']*charset\s*=\s*([\w.-]+)", head, re.I)
    candidates = [declared.group(1)] if declared else list(HTML_ENCODINGS[:4])
    detected_encoding = None
    try:
        from charset_normalizer import from_bytes
        detected = from_bytes(raw).best()
        if detected and detected.encoding:
            detected_encoding = detected.encoding
    except ImportError:
        pass
    if detected_encoding:
        candidates.append(detected_encoding)
    candidates.extend(HTML_ENCODINGS[4:])
    failures = []
    for encoding in dict.fromkeys(candidates):
        try:
            text = raw.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            failures.append(f"{encoding}: {exc}")
            if declared and encoding.lower().replace("-", "") in {"utf8", "utf"}:
                mixed = raw.decode(encoding, errors="surrogateescape")
                mixed = "".join(value if not 0xDC80 <= ord(value) <= 0xDCFF else f"\\x{ord(value) - 0xDC00:02x}" for value in mixed)
                stats["decode_failures"].append({"file": str(path), "encoding": "utf-8+surrogateescape",
                                                  "reason": f"declared {encoding} had malformed byte sequences: {exc}"})
                stats["degraded_pages"] = stats.get("degraded_pages", 0) + 1
                return mixed
            continue
        stats["encodings"][encoding] = stats["encodings"].get(encoding, 0) + 1
        if "�" not in text:
            if declared and encoding.lower() != declared.group(1).lower():
                stats["decode_failures"].append({"file": str(path), "encoding": encoding,
                                                  "reason": f"declared {declared.group(1)} failed; fallback succeeded"})
            return text
        failures.append(f"{encoding}: decoded with replacement character")
    reason = "; ".join(failures[-5:])
    stats["decode_failures"].append({"file": str(path), "encoding": candidates[0] if candidates else None, "reason": reason})
    encoding = candidates[0] if candidates else "utf-8"
    try:
        text = raw.decode(encoding, errors="backslashreplace")
    except LookupError as exc:
        stats["decode_failures"][-1]["reason"] += f"; fallback failed: {exc}"
        raise UnicodeError(f"Unable to decode {path.name}: {reason}") from exc
    stats["degraded_pages"] = stats.get("degraded_pages", 0) + 1
    return text


def _decompile(chm_path: Path, root: Path) -> None:
    hh = shutil.which("hh.exe") or shutil.which("hh")
    if not hh:
        raise RuntimeError("CHM requires Windows hh.exe; hh.exe was not found on PATH")
    root.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([hh, "-decompile", str(root), str(chm_path)], check=True,
                       capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("hh.exe CHM decompile timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"hh.exe CHM decompile failed: {detail}") from exc


def _toc_order(root: Path, stats: dict) -> list[Path]:
    """Use the compiled HTML Help table of contents when available."""
    hhc = next(iter(sorted(path for path in root.rglob("*") if path.suffix.lower() == ".hhc")), None)
    if not hhc:
        return []
    text = _decode_html(hhc.read_bytes(), hhc, stats)
    names = re.findall(r'<param\s+name=["\']Local["\']\s+value=["\']([^"\']+)', text, re.I)
    result = []
    for name in names:
        candidate = (root / unquote(name.replace("\\", "/"))).resolve()
        if candidate.is_file() and candidate.suffix.lower() in {".html", ".htm"} and candidate not in result:
            result.append(candidate)
    return result


def _inline(node, root: Path, image_dir: Path, base_dir: Path | None = None, stats: dict | None = None, code_mode: bool = False) -> str:
    from bs4 import NavigableString, Tag
    if isinstance(node, NavigableString):
        return str(node).replace("\xa0", " ")
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name == "br":
        return "\n"
    if name == "img":
        if stats is not None:
            stats["images_found"] += 1
        src = str(node.get("src") or node.get("data-src") or "")
        parsed = urlparse(src)
        if parsed.scheme and parsed.scheme not in {"file"}:
            return ""
        source = ((base_dir or root) / unquote(parsed.path or src).replace("/", "\\")).resolve()
        if not source.is_file():
            if stats is not None:
                stats["image_warnings"].append({"file": str(base_dir or root), "src": src})
            return f"![{node.get('alt', '')}]({src})" if src else ""
        digest = hashlib.sha1(str(source.relative_to(root)).encode("utf-8", errors="ignore")).hexdigest()[:10]
        target = image_dir / f"{digest}_{source.name}"
        if not target.exists():
            shutil.copy2(source, target)
        return f"![{node.get('alt', '')}](assets/images/{target.name})"
    content = "".join(_inline(child, root, image_dir, base_dir, stats, code_mode) for child in node.children)
    if name in {"strong", "b"}:
        return f"**{content.strip()}**"
    if name in {"em", "i"}:
        return f"*{content.strip()}*"
    if name == "a" and not code_mode:
        href = str(node.get("href") or "")
        return f"[{content.strip()}]({href})" if href else content
    return content


def _table(table, root: Path, image_dir: Path, base_dir: Path | None = None, stats: dict | None = None) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if cells:
            rows.append([re.sub(r"\s+", " ", _inline(cell, root, image_dir, base_dir, stats)).strip().replace("|", "\\|") for cell in cells])
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    if len(rows) == 1:
        rows.append([""] * width)
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(lines)


def _page_blocks(page: Path, root: Path, image_dir: Path, page_number: int, order_start: int, stats: dict) -> tuple[list[Block], int, str | None]:
    from bs4 import BeautifulSoup
    text = _decode_html(page.read_bytes(), page, stats)
    stats["html_parsed"] += 1
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for selector in ("#top", ".tabs", ".navpath", "address.footer", ".footer"):
        for tag in soup.select(selector):
            tag.decompose()
    body = soup.body or soup
    blocks: list[Block] = []
    order = order_start
    title = body.find("h1") or body.select_one(".headertitle .title") or soup.find("title")
    page_title = title.get_text(" ", strip=True) if title else None
    # Doxygen emits code as div.fragment > div.line, not as <pre>.
    fragments = list(body.select(".fragment"))
    for fragment in fragments:
        for line in fragment.select(".lineno"):
            line.decompose()
        code = "\n".join(_inline(line, root, image_dir, page.parent, stats, True).rstrip() for line in fragment.select(".line"))
        if code.strip():
            blocks.append(Block(code, page_number, order=order, kind="code", source_page=str(page.relative_to(root)), title=page_title))
            order += 1
        fragment.decompose()
        stats["code_blocks"] += 1
    elements = body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "table", "p", "li", "blockquote", "img"], recursive=True)
    if page_title and not body.find("h1"):
        blocks.insert(0, Block(page_title, page_number, heading_level=1, order=order, kind="heading", source_page=str(page.relative_to(root)), title=page_title))
        order += 1
    for element in elements:
        # Nested elements are rendered by their parent.
        if element.name == "img" and element.find_parent(["p", "li", "blockquote", "table"], recursive=False):
            continue
        if element.find_parent(["pre", "table", "li", "blockquote", "code"], recursive=False):
            continue
        kind = "text"
        level = None
        if element.name.startswith("h"):
            kind, level = "heading", int(element.name[1])
            text = _inline(element, root, image_dir, page.parent, stats).strip()
        elif element.name == "pre":
            kind = "code"
            text = "".join(element.strings)
            stats["code_blocks"] += 1
        elif element.name == "code":
            kind = "code"
            text = "".join(element.strings)
            stats["code_blocks"] += 1
        elif element.name == "table":
            kind, text = "table", _table(element, root, image_dir, page.parent, stats)
        else:
            text = _inline(element, root, image_dir, page.parent, stats).strip()
        while re.search(r"(?i)(?<![\w])fragment(?![\w(])\s*$", text):
            text = re.sub(r"(?i)(?<![\w])fragment(?![\w(])\s*$", "", text).rstrip()
        if re.sub(r"\s+", "", text).lower() in {"首页", "相关页面", "模块", "结构体", "示例", "fragment"} or "copyright" in text.lower():
            continue
        if not text.strip():
            continue
        blocks.append(Block(text=text.strip() if kind != "code" else text.rstrip("\n"), page=page_number,
                            heading_level=level, order=order, kind=kind, source_page=str(page.relative_to(root)), title=page_title))
        order += 1
    return blocks, order, page_title


def _split_large_chunks(chunks: list[dict], limit: int) -> list[dict]:
    """Split CHM-only oversized paragraph/table/code payloads at safe boundaries."""
    result: list[dict] = []
    for original in chunks:
        content = str(original.get("content") or "")
        if len(content) <= limit:
            result.append(dict(original))
            continue
        parts: list[str] = []
        if content.lstrip().startswith("|"):
            lines = content.splitlines()
            header = lines[:2] if len(lines) >= 2 else []
            current = list(header)
            for line in lines[2:]:
                if len("\n".join(current + [line])) > limit and len(current) > len(header):
                    parts.append("\n".join(current))
                    current = list(header)
                current.append(line)
            if len(current) > len(header):
                parts.append("\n".join(current))
        else:
            units = re.split(r"(?<=\n\n)|(?<=\n)", content)
            current = ""
            for unit in units:
                if current and len(current) + len(unit) > limit:
                    parts.append(current.strip())
                    current = ""
                if len(unit) > limit and unit.startswith("```"):
                    code_lines = unit.splitlines()
                    current_code = []
                    for line in code_lines:
                        if current_code and len("\n".join(current_code + [line])) > limit:
                            parts.append("\n".join(current_code))
                            current_code = []
                        current_code.append(line)
                    if current_code:
                        parts.append("\n".join(current_code))
                else:
                    current += unit
            if current.strip():
                parts.append(current.strip())
        if not parts:
            parts = [content[index:index + limit] for index in range(0, len(content), limit)]
        for part in parts:
            item = dict(original)
            item["content"] = part
            result.append(item)
    for index, chunk in enumerate(result, 1):
        chunk["chunk_id"] = f"chunk-{index:04d}"
    return result


def parse_chm(chm_path: Path, output_dir: Path, *, max_chars: int = 1800,
              metadata: dict | None = None) -> ParsedDocument:
    """Decompile and parse a CHM into the common ParsedDocument contract."""
    chm_path = Path(chm_path).resolve()
    if not chm_path.is_file() or chm_path.suffix.lower() != ".chm":
        raise FileNotFoundError(f"CHM not found: {chm_path}")
    output_dir = Path(output_dir)
    stats = {"html_discovered": 0, "html_parsed": 0, "html_failed": 0, "degraded_pages": 0, "encodings": {}, "decode_failures": [],
             "images_found": 0, "images_copied": 0, "image_warnings": [], "code_blocks": 0}
    with tempfile.TemporaryDirectory(prefix="zrdds_chm_") as temp:
        root = Path(temp)
        _decompile(chm_path, root)
        image_dir = output_dir / "assets" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        pages = _toc_order(root, stats)
        discovered = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".html", ".htm"})
        stats["html_discovered"] = len(discovered)
        pages += [page for page in discovered if page not in pages]
        if not pages:
            raise RuntimeError("CHM decompiled successfully but no HTML/HTM pages were found")
        blocks: list[Block] = []
        order = 0
        first_title = None
        for number, page in enumerate(pages, start=1):
            try:
                page_blocks, order, page_title = _page_blocks(page, root, image_dir, number, order, stats)
            except UnicodeError as exc:
                stats["html_failed"] += 1
                LOGGER.warning("Skipping undecodable CHM page %s: %s", page.name, exc)
                continue
            blocks.extend(page_blocks)
            first_title = first_title or page_title
    meta = dict(metadata or {})
    if not meta.get("product") and chm_path.stem.upper().startswith("ZRDDS"):
        meta["product"] = "ZRDDS"
    if not meta.get("language"):
        language_match = re.search(r"(?:^|[_-])([A-Za-z]{1,8})(?:[_-]UserManual|$)", chm_path.stem, re.I)
        if language_match:
            meta["language"] = language_match.group(1)
    if not meta.get("doc_type") and "manual" in chm_path.stem.lower():
        meta["doc_type"] = "user_manual"
    meta.update({"source_file": chm_path.name, "title": meta.get("title") or first_title or chm_path.stem})
    chunks = split_chunks(chm_path.name, blocks, max_chars, meta)
    chunks = _split_large_chunks(chunks, max(1200, min(max_chars, 3800)))
    stats["images_copied"] = len(list(image_dir.iterdir()))
    stats["max_chunk_chars"] = max((len(str(item.get("content") or "")) for item in chunks), default=0)
    stats["avg_chunk_chars"] = round(sum(len(str(item.get("content") or "")) for item in chunks) / len(chunks), 2) if chunks else 0
    language = str(meta.get("language") or "text").lower()
    markdown = "# " + str(meta["title"]) + "\n\n" + "\n\n".join(
        ("#" * block.heading_level + " " + block.text) if block.heading_level else (f"```{language}\n" + block.text + "\n```" if block.kind == "code" else block.text)
        for block in blocks
    ) + "\n"
    stats["replacement_characters"] = markdown.count("�")
    stats["cross_html_heading_carryover"] = False
    (output_dir / "chm_parse_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return ParsedDocument(chm_path.name, blocks, chunks, markdown, source_path=str(chm_path),
                          product=meta.get("product"), version=meta.get("version"), doc_type=meta.get("doc_type"))


__all__ = ["parse_chm"]
