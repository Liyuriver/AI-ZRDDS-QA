import json
import os
import re
from pathlib import Path
from typing import Any, Dict

import httpx
from dotenv import load_dotenv

load_dotenv()


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

    def _extract_sources(self, data: Dict[str, Any]) -> list[dict]:
        metadata = data.get("metadata") or {}

        resources = (
            metadata.get("retriever_resources")
            or metadata.get("retrieverResources")
            or []
        )

        sources = []

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

        return sources

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
            # 当前后端 conversation_id 不是 Dify conversation_id，暂时不要直接传给 Dify
            "conversation_id": "",
            "user": user_id or "test-user",
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=60.0,
            trust_env=False,
        ) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()

        return {
            "answer": self._clean_answer(data.get("answer", "")),
            "status": "answered",
            "sources": self._extract_sources(data),
        }
