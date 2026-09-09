import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from app.services.answer_validation_service import validate_answer
from app.config import DIFY_TOP_K
from app.services.metadata.metadata_service import find_document_metadata
from app.services.query_rewrite_service import rewrite_query
from app.services.retrieval.evidence_service import analyze_evidence_support

load_dotenv()
logger = logging.getLogger(__name__)

load_dotenv()
logger = logging.getLogger(__name__)


DIFY_QUERY_MAX_LENGTH = 250
_TECHNICAL_IDENTIFIER_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_]*(?:::[A-Za-z][A-Za-z0-9_]*(?:\(\))?)?"
)
# 参与"与原问题直接相关"判定的英文 token 最小长度与停用词
_TOKEN_MIN_LENGTH = 3
_ENGLISH_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "these",
    "those", "from", "what", "when", "where", "which", "will", "would", "should",
    "can", "could", "does", "have", "has", "how", "why", "its", "into", "about",
    "between", "after", "before", "than", "then", "there", "their", "them", "they",
    "your", "you", "our", "out", "not", "but", "all", "any", "some", "such", "also",
    "only", "over", "under", "same", "each", "both", "one", "two", "via", "etc",
})


def _normalize_query_text(text: str) -> str:
    """统一空白，避免 token 级别的重复/漂移噪声。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _original_word_tokens(original: str) -> frozenset[str]:
    """原问题中的英文词（小写、去停用词），作为"与原问题直接相关"的判定依据。"""
    tokens: set[str] = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_]*", str(original or "")):
        lowered = word.lower()
        if len(lowered) >= _TOKEN_MIN_LENGTH and lowered not in _ENGLISH_STOPWORDS:
            tokens.add(lowered)
    return frozenset(tokens)


def _stems_overlap(term: str, tokens: frozenset[str]) -> bool:
    """term 与原始问题是否存在词干/前缀重叠（通用相关性代理，非单题规则）。"""
    t = str(term or "").casefold()
    for tok in tokens:
        if len(tok) >= _TOKEN_MIN_LENGTH and (
            t.startswith(tok) or tok.startswith(t) or tok in t or t in tok
        ):
            return True
    return False


def _technical_terms(text: str) -> list[str]:
    """Extract stable API/type/enum identifiers without expanding prose."""
    terms: list[str] = []
    for candidate in _TECHNICAL_IDENTIFIER_RE.findall(str(text or "")):
        bare = candidate.split("::")[-1].removesuffix("()")
        is_qualified = "::" in candidate
        is_snake = "_" in candidate
        is_enum = is_snake and candidate.upper() == candidate
        is_camel = any(char.isupper() for char in bare[1:])
        if not (is_qualified or is_snake or is_enum or is_camel):
            continue
        if candidate.casefold() not in {item.casefold() for item in terms}:
            terms.append(candidate)
        if is_qualified and bare.casefold() not in {item.casefold() for item in terms}:
            terms.append(bare)
    return terms


def _classify_term(term: str, original: str, original_tokens: frozenset[str]) -> int:
    """通用技术词优先级：1=primary（必须保留）3=secondary（长度允许时保留）4=related（默认丢弃）。"""
    bare = term.split("::")[-1].removesuffix("()")
    is_qualified = "::" in term or term.endswith("()")
    is_enum = "_" in term and term.upper() == term
    is_camel = (not is_enum) and any(char.isupper() for char in bare[1:]) and "_" not in bare
    is_snake = ("_" in term) and not is_enum
    is_plain_word = re.fullmatch(r"[A-Za-z]+", bare) is not None
    is_chinese = any("\u4e00" <= char <= "\u9fff" for char in term)

    if is_chinese:
        # 中文扩展词只在原问题中直接出现时保留，避免随触发词无限扩展。
        return 1 if term in original else 4
    if is_qualified or is_enum or term.startswith("DDS_") or is_camel:
        return 1
    if is_snake:
        # 方法名：与原问题词干关联才算高价值；否则视为弱相关扩展。
        return 1 if _stems_overlap(bare, original_tokens) else 4
    if is_plain_word:
        if term.casefold() in original.casefold():
            return 1
        # 标准单字术语（wait/read/take 等）：中等价值，长度允许时保留。
        return 3
    return 4


def _phrase_is_valuable(phrase: str, original_tokens: frozenset[str], primary: list[str]) -> bool:
    """多词语义 gloss 是否值得保留：包含核心技术词，或与原问题词干重叠。"""
    lowered = str(phrase or "").casefold()
    if _stems_overlap(phrase, original_tokens):
        return True
    return any(primary_term.casefold() in lowered for primary_term in primary)


def _compress_oversized_query(original: str, ordered: list[str], max_length: int) -> str:
    """原始问题本身超长时：先保留核心技术词/语义短语，再用自然语言填充剩余预算。
    这是"压缩自然语言"步骤，不是盲目的字符切片。"""
    packed = ""
    for item in ordered:
        candidate = f"{packed} {item}".strip() if packed else item
        if len(candidate) <= max_length:
            packed = candidate
        else:
            break
    remaining = max_length - len(packed) - (1 if packed else 0)
    if remaining <= 0:
        return packed
    for word in re.findall(r"[A-Za-z]+|[0-9]+|[\u4e00-\u9fff]+", original):
        candidate = f"{packed} {word}".strip()
        if len(candidate) > max_length:
            break
        packed = candidate
    return packed


def build_dify_query(
    original_query: str,
    rewritten_query: str | None = None,
    *,
    max_length: int = DIFY_QUERY_MAX_LENGTH,
    trace: dict | None = None,
) -> str:
    """构建受长度约束的 Dify 查询，统一处理中文/英文/中英混合问题。

    最终查询由四部分组成（按优先级组装）：
      1. 原始问题核心语义（压缩后的原问题）
      2. 核心技术标识符（CamelCase / snake_case / ALL_CAPS_ENUM / DDS_* / Class::method）
      3. 高价值语义短语（与核心概念或原问题直接相关的 rewrite gloss）
      4. 必要的标准技术术语（次要单字术语，长度允许时保留）

    压缩顺序：去重 → 丢弃 related → 丢弃低价值 secondary → 压缩自然语言。
    """
    original = _normalize_query_text(original_query)
    rewritten = _normalize_query_text(rewritten_query)
    original_tokens = _original_word_tokens(original)

    # 复用现有 QueryPlan/rewrite 的结构化信息（不重复实现第二套改写系统）。
    plan = rewrite_query(original) if original else None
    expansion_terms = list(plan.expansion_terms) if plan else []
    rewrite_single_terms: list[str] = []
    if plan:
        for term in (
            list(plan.core_terms) + list(plan.technical_entities)
            + list(plan.scenario_terms) + expansion_terms
        ):
            if " " in term.strip():
                continue  # 多词 gloss 走语义短语通道
            if term.casefold() in original.casefold():
                continue  # 已在原问题中，无需重复加入
            if term.casefold() not in {item.casefold() for item in rewrite_single_terms}:
                rewrite_single_terms.append(term)

    # 技术标识符：从 原问题 + rewrite 全文 中提取并去重。
    identifiers = _technical_terms(f"{original} {rewritten}")

    # 归类：primary / secondary / related。
    primary: list[str] = []
    secondary: list[str] = []
    related: list[str] = []
    for term in identifiers:
        priority = _classify_term(term, original, original_tokens)
        (primary if priority == 1 else secondary if priority == 3 else related).append(term)
    for term in rewrite_single_terms:
        if " " in term.strip():
            continue  # 多词 gloss 走语义短语通道
        if term.casefold() in {item.casefold() for item in primary} or term.casefold() in {
            item.casefold() for item in secondary
        } or term.casefold() in {item.casefold() for item in related}:
            continue
        priority = _classify_term(term, original, original_tokens)
        (primary if priority == 1 else secondary if priority == 3 else related).append(term)

    # 通用降级规则：与原问题无词干关联、但包含已保留核心概念的 API 名，
    # 视为有价值的扩展降为 secondary（长度允许时保留）；无关扩展保持 related 丢弃。
    rescued: list[str] = []
    for term in list(related):
        lowered = term.casefold()
        if any(primary_term.casefold() in lowered for primary_term in primary):
            related.remove(term)
            secondary.append(term)
            rescued.append(term)

    # 语义短语：只保留与核心概念或原问题相关的 gloss。
    phrases = [term for term in expansion_terms if " " in term.strip()]
    kept_phrases = [phrase for phrase in phrases if _phrase_is_valuable(phrase, original_tokens, primary)]
    dropped_phrases = [phrase for phrase in phrases if phrase not in kept_phrases]

    # 组装：同层内更长的词先占位（更长 = 信息更多，并能覆盖短重复）。
    ordered: list[str] = []
    ordered += sorted(primary, key=lambda term: (-len(term),))
    ordered += kept_phrases
    ordered += sorted(secondary, key=lambda term: (-len(term),))

    query = original
    dropped: list[str] = list(dropped_phrases) + related
    for item in ordered:
        if len(query) >= max_length:
            break
        if item.casefold() in query.casefold():
            continue  # 包含式去重：read / read() / DataReader::read() 只保留一次
        candidate = f"{query} {item}".strip()
        if len(candidate) > max_length:
            dropped.append(item)
            continue
        query = candidate

    if len(query) > max_length:
        # 仅当原问题本身超长时触发：保留核心技术词 + 语义短语，压缩自然语言。
        query = _compress_oversized_query(original, ordered, max_length)

    if trace is not None:
        trace.update({
            "core_terms": list(plan.core_terms) if plan else [],
            "technical_terms": list(dict.fromkeys(primary + secondary)),
            "semantic_phrases": kept_phrases,
            "dropped_terms": list(dict.fromkeys(dropped)),
            "final_dify_query": query,
            "final_length": len(query),
        })
    return query


class AIServiceError(RuntimeError):
    """Raised when Dify cannot complete a chat request safely."""


class AIClient:
    def __init__(self):
        self.base_url = (os.getenv("DIFY_API_BASE") or "").rstrip("/")
        self.api_key = (
            os.getenv("DIFY_APP_API_KEY")
            or os.getenv("DIFY_API_KEY")
        )
        self.last_retrieval_trace: dict[str, Any] = {}

        # 当前文件：backend/app/services/ai_client.py
        backend_root = Path(__file__).resolve().parents[2]
        self.hybrid_root = backend_root / "data" / "hybrid"
        self.segment_map_path = self.hybrid_root / "dify_segment_map.json"

        self.segment_map = self._load_segment_map()
        self._enrich_map_with_chunk_content()

        # 队友的预处理结果中，图片说明可能不直接写在 chunks.jsonl，
        # 而是在 image_manifest.json / image_matches.json /
        # visual_registry.json 等结构化文件里。
        # 这里统一建立图片元数据索引，供 caption 回退使用。
        self.image_meta_index = self._load_image_metadata_index()

        # 本地开发默认由 FastAPI 暴露图片；部署时可通过环境变量覆盖。
        self.image_base_url = (
            os.getenv("IMAGE_BASE_URL")
            or "http://127.0.0.1:8000/static/hybrid"
        ).rstrip("/")

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", str(text)).strip()

    @staticmethod
    def _normalize_document_name(name: str) -> str:
        if not name:
            return ""
        name = str(name).strip()
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        return name

    def _load_segment_map(self) -> list[dict]:
        if not self.segment_map_path.exists():
            return []

        try:
            with self.segment_map_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _enrich_map_with_chunk_content(self) -> None:
        """
        dify_segment_map.json 里目前没有 content。
        这里根据 bundle_dir + chunk_id 自动读取各自 chunks.jsonl，
        给内存中的映射补上 content，不修改磁盘文件。
        """
        if not self.segment_map:
            return

        by_bundle: dict[str, dict[str, str]] = {}

        for item in self.segment_map:
            bundle_dir = item.get("bundle_dir")
            chunk_id = item.get("chunk_id")

            if not bundle_dir or not chunk_id:
                continue

            if bundle_dir not in by_bundle:
                jsonl_path = self.hybrid_root / bundle_dir / "chunks.jsonl"
                chunk_contents: dict[str, str] = {}

                if jsonl_path.exists():
                    try:
                        with jsonl_path.open("r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                row = json.loads(line)
                                cid = row.get("chunk_id")
                                content = row.get("content")
                                if cid and content:
                                    chunk_contents[str(cid)] = str(content)
                    except Exception:
                        chunk_contents = {}

                by_bundle[bundle_dir] = chunk_contents

            item["_content"] = by_bundle[bundle_dir].get(str(chunk_id), "")

    @staticmethod
    def _first_nonempty_text(data: dict) -> str:
        """
        取适合作为前端 caption 的简短说明。

        当前预处理格式中，很多截图的顶层 caption 为空，
        真正的图像说明位于 image_manifest.json 的：
            vlm.description
        所以这里显式支持嵌套 vlm 字段。
        """
        for key in (
            "caption",
            "image_text",
            "description",
            "summary",
            "alt_text",
            "title",
            "text",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        vlm = data.get("vlm")
        if isinstance(vlm, dict):
            # VLM caption 经常也是空字符串，所以优先尝试 caption，
            # 再使用 description 作为简洁图注。
            for key in ("caption", "description"):
                value = vlm.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return ""

    def _load_image_metadata_index(self) -> dict[str, dict]:
        """
        扫描每个 hybrid 文档目录中的结构化图片元数据文件。

        支持：
        - image_manifest.json
        - image_matches.json
        - visual_registry.json

        不依赖某一种固定 JSON 外层结构，而是递归寻找包含
        image_id / path 等字段的对象。
        """
        index: dict[str, dict] = {}

        candidate_files = (
            "image_manifest.json",
            "image_matches.json",
            "visual_registry.json",
        )

        def walk(node, bundle_dir: str):
            if isinstance(node, dict):
                image_id = (
                    node.get("image_id")
                    or node.get("id")
                    or node.get("imageId")
                )
                image_path = (
                    node.get("path")
                    or node.get("image_path")
                    or node.get("file_path")
                )

                caption = self._first_nonempty_text(node)

                if image_id or image_path:
                    meta = dict(node)
                    meta["_bundle_dir"] = bundle_dir
                    if caption and not meta.get("caption"):
                        meta["caption"] = caption

                    def save_meta(key: str, candidate: dict) -> None:
                        """
                        同一图片可能同时出现在 manifest / matches / registry。
                        保留信息更丰富的那份，避免后读取的 visual_registry
                        把包含 vlm.description 的 manifest 记录覆盖掉。
                        """
                        existing = index.get(key)

                        if existing is None:
                            index[key] = candidate
                            return

                        existing_caption = self._first_nonempty_text(existing)
                        candidate_caption = self._first_nonempty_text(candidate)

                        # 有说明的优先于无说明的。
                        if candidate_caption and not existing_caption:
                            index[key] = candidate
                            return

                        # 都有或都没有说明时，优先保留包含 VLM 结果的记录。
                        if (
                            isinstance(candidate.get("vlm"), dict)
                            and not isinstance(existing.get("vlm"), dict)
                        ):
                            index[key] = candidate

                    if image_id:
                        save_meta(
                            f"id::{bundle_dir}::{image_id}",
                            meta,
                        )

                    if image_path:
                        norm_path = str(image_path).replace("\\\\", "/").lstrip("/")
                        save_meta(
                            f"path::{bundle_dir}::{norm_path}",
                            meta,
                        )

                for value in node.values():
                    walk(value, bundle_dir)

            elif isinstance(node, list):
                for value in node:
                    walk(value, bundle_dir)

        if not self.hybrid_root.exists():
            return index

        for bundle in self.hybrid_root.iterdir():
            if not bundle.is_dir():
                continue

            for filename in candidate_files:
                path = bundle / filename
                if not path.exists():
                    continue

                try:
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    walk(data, bundle.name)
                except Exception:
                    # 某个辅助文件异常不应影响问答主流程
                    continue

        return index

    def _resolve_image_caption(
        self,
        bundle_dir: str,
        image: dict,
    ) -> str:
        """
        caption 获取顺序：
        1. chunks.jsonl / dify_segment_map 中现成 caption
        2. image_text 等现成说明
        3. image_manifest / image_matches / visual_registry 中同图元数据
        """
        direct = self._first_nonempty_text(image)
        if direct:
            return direct

        image_id = image.get("image_id")
        image_path = image.get("path")

        candidates = []

        if image_id:
            candidates.append(
                self.image_meta_index.get(
                    f"id::{bundle_dir}::{image_id}"
                )
            )

        if image_path:
            norm_path = str(image_path).replace("\\", "/").lstrip("/")
            candidates.append(
                self.image_meta_index.get(
                    f"path::{bundle_dir}::{norm_path}"
                )
            )

        for meta in candidates:
            if isinstance(meta, dict):
                caption = self._first_nonempty_text(meta)
                if caption:
                    return caption

        return ""

    @staticmethod
    def _clean_answer(answer: str) -> str:
        if not answer:
            return ""

        answer = re.sub(
            r"<think>.*?</think>",
            "",
            answer,
            flags=re.S,
        )
        return answer.strip()

    @staticmethod
    def _get_nested(data: dict, *path):
        current = data
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _extract_metadata_value(cls, item: dict, key: str):
        """Read an evidence metadata value from supported Dify nesting shapes."""
        paths = (
            (key,),
            ("metadata", key),
            ("document_metadata", key),
            ("segment", "metadata", key),
            ("retriever_resource", "metadata", key),
        )
        for path in paths:
            value = cls._get_nested(item, *path)
            if value is not None:
                return value
        return None

    def _find_mapping(
        self,
        resource: dict,
        quote: str,
        document_name: str,
    ) -> dict | None:
        """
        优先按 segment_id 匹配；
        若 Dify 当前版本没有返回 segment_id，则按
        document_name + quote/content 做回退匹配。
        """

        segment_id_candidates = [
            resource.get("segment_id"),
            resource.get("segmentId"),
            resource.get("document_segment_id"),
            self._get_nested(resource, "segment", "id"),
            self._get_nested(resource, "metadata", "segment_id"),
            self._get_nested(resource, "metadata", "segmentId"),
        ]

        for segment_id in segment_id_candidates:
            if not segment_id:
                continue
            for item in self.segment_map:
                if item.get("segment_id") == segment_id:
                    return item

        # 回退：文档名 + 内容匹配
        norm_quote = self._normalize_text(quote)
        norm_doc = self._normalize_document_name(document_name)

        best = None
        best_score = 0.0

        for item in self.segment_map:
            map_doc = self._normalize_document_name(item.get("document", ""))

            if norm_doc and map_doc and norm_doc != map_doc:
                continue

            content = self._normalize_text(item.get("_content", ""))
            if not content or not norm_quote:
                continue

            if content == norm_quote:
                return item

            if norm_quote in content or content in norm_quote:
                shorter = min(len(norm_quote), len(content))
                longer = max(len(norm_quote), len(content))
                score = shorter / longer if longer else 0.0

                if score > best_score:
                    best_score = score
                    best = item

        return best


    def _build_image_url(self, bundle_dir: str, image_path: str) -> str:
        """把映射里的 bundle_dir + 相对图片路径转换成可访问 URL。"""
        bundle = quote(str(bundle_dir).replace("\\", "/").strip("/"), safe="")
        path = quote(str(image_path).replace("\\", "/").lstrip("/"), safe="/")
        return f"{self.image_base_url}/{bundle}/{path}"

    def _images_from_mapping(self, mapping: dict | None) -> list[dict]:
        if not mapping:
            return []

        bundle_dir = mapping.get("bundle_dir")
        raw_images = mapping.get("images") or []
        if not bundle_dir or not isinstance(raw_images, list):
            return []

        result = []
        for image in raw_images:
            if not isinstance(image, dict):
                continue

            image_path = image.get("path")
            if not image_path:
                continue

            # 只返回磁盘上真实存在的图片，避免前端收到坏链接。
            local_path = (self.hybrid_root / bundle_dir / image_path).resolve()
            try:
                local_path.relative_to(self.hybrid_root.resolve())
            except ValueError:
                continue

            if not local_path.exists() or not local_path.is_file():
                continue

            result.append(
                {
                    "image_id": image.get("image_id"),
                    "url": self._build_image_url(bundle_dir, image_path),
                    "caption": self._resolve_image_caption(bundle_dir, image),
                    "page": image.get("page") or mapping.get("page") or 0,
                    "document": mapping.get("document") or "",
                    "section": mapping.get("section") or "",
                }
            )

        return result

    def _extract_sources(self, data: Dict[str, Any]) -> list[dict]:
        metadata = data.get("metadata") or {}

        resources = (
            metadata.get("retriever_resources")
            or metadata.get("retrieverResources")
            or []
        )

        sources = []
        images = []
        seen_images = set()

        for citation_index, item in enumerate(resources, 1):
            if not isinstance(item, dict):
                continue

            document = (
                item.get("document_name")
                or item.get("document")
                or ""
            )

            quote = (
                item.get("content")
                or item.get("quote")
                or ""
            )

            mapping = self._find_mapping(
                resource=item,
                quote=quote,
                document_name=document,
            )

            if mapping:
                document = mapping.get("document") or document
                section = mapping.get("section") or ""
                page = mapping.get("page") or 0
            else:
                section = (
                    item.get("segment_name")
                    or item.get("section")
                    or ""
                )
                page = item.get("page") or 0

            segment_id = item.get("segment_id") or item.get("segmentId")
            chunk_id = item.get("chunk_id") or segment_id
            source = {
                    "document": document,
                    "document_id": item.get("document_id") or item.get("dataset_id"),
                    "source_id": segment_id or chunk_id,
                    "source_type": "dify",
                    "citation_index": citation_index,
                    "source_file": document,
                    "chunk_id": chunk_id,
                    "segment_id": segment_id,
                    "position": item.get("position"),
                    "section": section,
                    "page": page,
                    "quote": quote,
                    "version": self._extract_metadata_value(item, "version") or (mapping or {}).get("version"),
                }
            raw_score = item.get("rerank_score", item.get("retrieval_score", item.get("score")))
            if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
                source["raw_score"] = raw_score
                source["score"] = raw_score  # backward-compatible field
            sources.append(source)

            for image in self._images_from_mapping(mapping):
                dedupe_key = image.get("image_id") or image.get("url")
                if not dedupe_key or dedupe_key in seen_images:
                    continue
                seen_images.add(dedupe_key)
                images.append(image)

        sources = self._enrich_sources_with_backend_metadata(sources)
        # 防止一次返回太多图片；后续可改成配置项。
        return sources, images[:8]

    @staticmethod
    def _enrich_sources_with_backend_metadata(sources: list[dict]) -> list[dict]:
        """Fill missing evidence version from authoritative backend metadata."""
        enriched = []
        for source in sources:
            dify_version = source.get("version")
            metadata, match_method = find_document_metadata(
                document_id=source.get("document_id"),
                document_name=source.get("document"),
            )
            backend_version = metadata.version if metadata else None
            final_version = dify_version or backend_version
            if dify_version and backend_version and dify_version != backend_version:
                logger.warning(
                    "evidence_metadata_version_conflict document=%s dify_version=%s backend_metadata_version=%s",
                    source.get("document"), dify_version, backend_version,
                )
            logger.debug(
                "evidence metadata enrichment document=%s dify_version=%s backend_metadata_version=%s final_evidence_version=%s metadata_match_method=%s",
                source.get("document"), dify_version, backend_version, final_version, match_method,
            )
            item = dict(source)
            item["version"] = final_version
            enriched.append(item)
        return enriched

    @staticmethod
    def build_sources_from_evidence(evidence: list[dict]) -> list[dict]:
        """Build unified citation sources directly from final evidence.

        Dify evidence  -> source_type="dify",  source_id=segment_id
        Local/BM25 evidence -> source_type="local", source_id=chunk_id

        citation_index is 1-based and matches the [证据N] markers in
        external_context. Sources are never re-sorted after construction.
        """
        evidence = evidence or []
        sources: list[dict] = []
        for index, item in enumerate(evidence, 1):
            if not isinstance(item, dict):
                continue
            segment_id = item.get("segment_id")
            chunk_id = item.get("chunk_id")
            source_type = "dify" if segment_id else "local"
            source_id = segment_id if source_type == "dify" else chunk_id
            source = {
                "source_id": source_id,
                "source_type": source_type,
                "citation_index": index,
                "document": item.get("source_file", ""),
                "source_file": item.get("source_file", ""),
                "segment_id": segment_id,
                "chunk_id": chunk_id,
                "section": item.get("section", ""),
                "page": item.get("page", 0),
                "position": item.get("position"),
                "score": item.get("rerank_score", 0),
                "quote": item.get("content", ""),
                "version": item.get("version"),
            }
            sources.append(source)
            logger.debug(
                "source_mapping evidence_index=%s evidence_source_id=%s api_source_id=%s document=%s source_type=%s",
                index, source_id, source_id, item.get("source_file"), source_type,
            )
        return sources

    async def query(
        self,
        question: str,
        version: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        auxiliary_query: str | None = None,
        bm25_context: str | None = None,
        external_context: str | None = None,
        evidence: list[dict] | None = None,
        candidate_pool: list[dict] | None = None,
        required_facets: list[dict] | None = None,
        relation_facets: list[dict] | None = None,
        reasoning_trace: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:

        if not self.base_url:
            raise RuntimeError("缺少 DIFY_API_BASE")

        if not self.api_key:
            raise RuntimeError(
                "缺少 DIFY_APP_API_KEY（或兼容旧配置 DIFY_API_KEY）"
            )

        url = f"{self.base_url}/chat-messages"

        final_query = question
        evidence = evidence or []
        relation_facets = relation_facets or []
        reasoning_trace = reasoning_trace or analyze_evidence_support(question, evidence, required_facets or [], relation_facets)
        context = external_context or ""
        if reasoning_trace.get("compositionally_covered_facets") or reasoning_trace.get("relation_chain_supported"):
            final_query = (
                f"{question}\n\n"
                "回答约束：已提供多条可组合证据。请区分证据事实与有限工程推论，"
                "可使用“可能/风险”等措辞；不要仅因缺少逐字相同的场景原句而拒绝回答。"
            )
            context = (
                f"{context}\n\n[证据链推理规则]\n"
                "上述证据分别支持产物来源、职责与兼容性后果。可以将这些事实组合为带“可能”或“风险”的有限工程推论；"
                "不得补充证据中没有的机制、参数、错误码或确定性后果。"
            )
        payload = {
            "inputs": {"external_context": context},
            "query": final_query,
            "response_mode": "blocking",
            "conversation_id": conversation_id or "",
            "user": user_id or "test-user",
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        retryable_statuses = {400, 408, 409, 429, 500, 502, 503, 504}

        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    break

                except httpx.HTTPStatusError as exc:
                    if (
                        attempt == 0
                        and exc.response.status_code in retryable_statuses
                    ):
                        await asyncio.sleep(0.5)
                        continue

                    raise AIServiceError(
                        "Dify 暂时无法完成回答，请稍后重试"
                    ) from exc

                except httpx.RequestError as exc:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue

                    raise AIServiceError(
                        "Dify 连接失败，请稍后重试"
                    ) from exc

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AIServiceError("Dify 返回了无法解析的响应，请稍后重试") from exc

        if not isinstance(data, dict):
            raise AIServiceError("Dify 返回了无效响应，请稍后重试")

        # Always extract from Dify for images + fallback when no backend evidence.
        dify_sources, images = self._extract_sources(data)
        if evidence:
            # Primary: build sources directly from final evidence so citations
            # match external_context [证据N] even when Dify retriever_resources
            # is empty (evidence injected via external_context, not Dify retrieval).
            sources = self.build_sources_from_evidence(evidence)
        else:
            sources = dify_sources
        validation = validate_answer(
            self._clean_answer(data.get("answer", "")), evidence, question,
            candidate_pool=candidate_pool, required_facets=required_facets,
            relation_facets=relation_facets,
        )
        logger.info(
            "final evidence=%s validation=%s reasons=%s",
            [
                {
                    "source": source.get("source_file") or source.get("document"),
                    "section": source.get("section"),
                    "rank": source.get("rerank_rank"),
                }
                for source in evidence
            ],
            validation.status,
            validation.reasons,
        )

        answer = self._clean_answer(data.get("answer", ""))
        answer_status = "answered"
        if not answer:
            answer = "当前知识库中没有找到足够证据回答这个问题，请补充更具体的信息后重试。"
            answer_status = "insufficient_evidence"
        logger.debug(
            "Dify evidence diagnostics raw_dify_version=%s parsed_evidence_versions=%s",
            [self._extract_metadata_value(item, "version") for item in (
                (data.get("metadata") or {}).get("retriever_resources") or []
            ) if isinstance(item, dict)],
            [item.get("version") for item in sources],
        )

        return {
            "answer": answer,
            "status": answer_status,
            "answer_status": "ANSWER" if answer_status == "answered" else "NO_ANSWER",
            "sources": sources,
            "evidence": sources,
            "images": images,
            "dify_conversation_id": data.get("conversation_id") or conversation_id,
            "validation": {
                "status": validation.status,
                "reasons": list(validation.reasons),
                "missing_required_facets": list(validation.missing_required_facets),
                "negative_claim_facets": list(validation.negative_claim_facets),
                "compositional_refusal_facets": list(validation.compositional_refusal_facets),
                "missing_relations": list(validation.missing_relations),
                "missing_side_states": list(validation.missing_side_states),
                "contradicted_negative_claims": list(validation.contradicted_negative_claims),
                "should_retry": validation.should_retry,
                "directly_covered_facets": reasoning_trace.get("directly_covered_facets", []),
                "compositionally_covered_facets": reasoning_trace.get("compositionally_covered_facets", []),
                "unsupported_facets": reasoning_trace.get("unsupported_facets", []),
                "facet_supporting_evidence_ids": reasoning_trace.get("facet_supporting_evidence_ids", {}),
                "reasoning_links": reasoning_trace.get("reasoning_links", []),
                "covered_relation_facets": reasoning_trace.get("covered_relation_facets", []),
                "uncovered_relation_facets": reasoning_trace.get("uncovered_relation_facets", []),
                "relation_supporting_evidence_ids": reasoning_trace.get("relation_supporting_evidence_ids", {}),
                "semantic_normalization": reasoning_trace.get("semantic_normalization", []),
                "missing_relations": list(validation.missing_relations),
                "missing_side_states": list(validation.missing_side_states),
                "contradicted_negative_claims": list(validation.contradicted_negative_claims),
            },
        }

    async def retrieve_knowledge(
        self,
        query: str,
        top_k: int = DIFY_TOP_K,
        *,
        original_query: str | None = None,
    ) -> list[dict]:
        """Call Dify's dataset retrieval API, never the chat answer endpoint."""
        trace: dict[str, Any] = {
            "original_query": original_query or query,
            "rewrite_query": query,
            "original_length": len(original_query or query),
            "rewrite_length": len(query),
        }
        dify_query = build_dify_query(original_query or query, query, trace=trace)
        trace.update({"dify_query": dify_query, "dify_query_length": len(dify_query)})
        self.last_retrieval_trace = trace
        dataset_id = os.getenv("DIFY_DATASET_ID")
        # Dataset retrieval uses a Knowledge/Dataset API key.  An App key is
        # intentionally not used as a fallback: the two Dify API surfaces have
        # different permissions and confusing them hides configuration errors.
        kb_key = os.getenv("DIFY_KB_API_KEY") or os.getenv("DIFY_DATASET_API_KEY")
        if not self.base_url:
            self.last_retrieval_trace.update({"status": "disabled", "http_status": None, "result_count": 0})
            logger.warning("DIFY_RETRIEVAL_DISABLED status=missing_base_url query_length=%s", len(dify_query))
            return []
        if not dataset_id or not kb_key:
            self.last_retrieval_trace.update({"status": "disabled", "http_status": None, "result_count": 0})
            logger.warning("DIFY_RETRIEVAL_DISABLED status=missing_credentials query_length=%s", len(dify_query))
            return []
        if len(dify_query) > DIFY_QUERY_MAX_LENGTH:
            self.last_retrieval_trace.update({"status": "blocked", "http_status": None, "result_count": 0,
                                              "error_type": "query_too_long"})
            logger.error("DIFY_RETRIEVAL_FAILED status=local_query_too_long error_type=query_too_long query_length=%s query_preview=%r",
                         len(dify_query), dify_query[:120])
            return []
        payload = {
            "query": dify_query,
            "retrieval_model": {
                "search_method": "hybrid_search",
                "reranking_enable": False,
                "top_k": top_k,
                "score_threshold_enabled": False,
            },
        }
        url = f"{self.base_url}/datasets/{dataset_id}/retrieve"
        headers = {"Authorization": f"Bearer {kb_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            body = response.json()
            records = body.get("records", []) if isinstance(body, dict) else []
        except httpx.HTTPStatusError as exc:
            error_type = "http_status_error"
            try:
                error_type = str(exc.response.json().get("code") or error_type)
            except (ValueError, TypeError):
                pass
            status = exc.response.status_code
            self.last_retrieval_trace.update({"status": "failed", "http_status": status,
                                              "result_count": 0, "error_type": error_type})
            logger.warning("DIFY_RETRIEVAL_FAILED status=%s error_type=%s query_length=%s query_preview=%r",
                           status, error_type, len(dify_query), dify_query[:120])
            return []
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            self.last_retrieval_trace.update({"status": "failed", "http_status": None,
                                              "result_count": 0, "error_type": type(exc).__name__})
            logger.warning("DIFY_RETRIEVAL_FAILED status=client_error error_type=%s query_length=%s query_preview=%r",
                           type(exc).__name__, len(dify_query), dify_query[:120])
            return []
        results = []
        for record in records:
            segment = record.get("segment") if isinstance(record, dict) else {}
            if not isinstance(segment, dict):
                continue
            metadata = segment.get("metadata") or {}
            document = segment.get("document") or record.get("document") or {}
            if isinstance(document, str):
                document_name = document
            else:
                document_name = document.get("name") or document.get("document_name") or ""
            results.append({
                "id": segment.get("id"),
                "chunk_id": segment.get("id") or segment.get("index_node_id"),
                "segment_id": segment.get("id"),
                "position": segment.get("position") or record.get("position") or metadata.get("position"),
                "document_id": segment.get("document_id") or (document.get("id") if isinstance(document, dict) else None),
                "source_file": segment.get("document_name") or document_name or metadata.get("source_file") or "",
                "section": segment.get("segment_name") or metadata.get("section") or "",
                "content": segment.get("content") or "",
                "raw_score": record.get("score", 0),
                "page": metadata.get("page") or 0,
            })
        results = results[:top_k]
        self.last_retrieval_trace.update({"status": "success", "http_status": 200, "result_count": len(results)})
        logger.info("DIFY_RETRIEVAL_SUCCESS status=200 query_length=%s result_count=%s top=%s",
                    len(dify_query), len(results),
                    [(item.get("source_file"), item.get("segment_id"), item.get("raw_score"))
                     for item in results[:3]])
        return results
