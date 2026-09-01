import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

load_dotenv()


class AIServiceError(RuntimeError):
    """Raised when Dify cannot complete a chat request safely."""


class AIClient:
    def __init__(self):
        self.base_url = (os.getenv("DIFY_API_BASE") or "").rstrip("/")
        self.api_key = (
            os.getenv("DIFY_APP_API_KEY")
            or os.getenv("DIFY_API_KEY")
        )

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

        for item in resources:
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

            sources.append(
                {
                    "document": document,
                    "section": section,
                    "page": page,
                    "score": item.get("score") or 0,
                    "quote": quote,
                }
            )

            for image in self._images_from_mapping(mapping):
                dedupe_key = image.get("image_id") or image.get("url")
                if not dedupe_key or dedupe_key in seen_images:
                    continue
                seen_images.add(dedupe_key)
                images.append(image)

        # 防止一次返回太多图片；后续可改成配置项。
        return sources, images[:8]

    async def query(
        self,
        question: str,
        version: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> Dict[str, Any]:

        if not self.base_url:
            raise RuntimeError("缺少 DIFY_API_BASE")

        if not self.api_key:
            raise RuntimeError(
                "缺少 DIFY_APP_API_KEY（或兼容旧配置 DIFY_API_KEY）"
            )

        url = f"{self.base_url}/chat-messages"

        payload = {
            "inputs": {},
            "query": question,
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

        data = response.json()

        sources, images = self._extract_sources(data)

        return {
            "answer": self._clean_answer(data.get("answer", "")),
            "status": "answered",
            "sources": sources,
            "images": images,
            "dify_conversation_id": data.get("conversation_id") or conversation_id,
        }
