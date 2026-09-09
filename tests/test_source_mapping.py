# -*- coding: utf-8 -*-
"""Unit tests for evidence-based source/citation mapping.

Verifies that build_sources_from_evidence() produces unified source objects
directly from final evidence, with stable source_id, correct source_type,
and citation_index matching [证据N] in external_context.
"""
import asyncio

import pytest

from app.services.ai_client import AIClient
from app.schemas.chat import ChatData


class TestBuildSourcesFromEvidence:
    def test_dify_evidence_gets_dify_type_and_segment_id(self):
        evidence = [
            {
                "source_file": "formal-15-04-10",
                "segment_id": "6f8b763c-34b5-43ea-a051-b15ce8d37566",
                "chunk_id": None,
                "section": "2.2.2.5.3.13",
                "page": 127,
                "content": "take_next_sample removes it from the DataReader so it is no longer accessible.",
                "rerank_score": 0.95,
            }
        ]
        sources = AIClient.build_sources_from_evidence(evidence)
        assert len(sources) == 1
        s = sources[0]
        assert s["source_type"] == "dify"
        assert s["source_id"] == "6f8b763c-34b5-43ea-a051-b15ce8d37566"
        assert s["segment_id"] == "6f8b763c-34b5-43ea-a051-b15ce8d37566"
        assert s["citation_index"] == 1
        assert s["document"] == "formal-15-04-10"
        assert "no longer accessible" in s["quote"]
        assert s["score"] == 0.95

    def test_local_evidence_gets_local_type_and_chunk_id(self):
        evidence = [
            {
                "source_file": "ZRDDS用户手册.pdf",
                "segment_id": None,
                "chunk_id": "chunk-0105",
                "section": "9.3.10.4",
                "page": 200,
                "content": "read_next_sample and take_next_sample",
                "rerank_score": 0.80,
            }
        ]
        sources = AIClient.build_sources_from_evidence(evidence)
        assert len(sources) == 1
        s = sources[0]
        assert s["source_type"] == "local"
        assert s["source_id"] == "chunk-0105"
        assert s["chunk_id"] == "chunk-0105"
        assert s["citation_index"] == 1

    def test_mixed_evidence_preserves_order_and_citation_index(self):
        evidence = [
            {"source_file": "doc-a", "segment_id": "seg-1", "chunk_id": None, "content": "A", "rerank_score": 0.9},
            {"source_file": "doc-b", "segment_id": None, "chunk_id": "chunk-2", "content": "B", "rerank_score": 0.8},
            {"source_file": "doc-c", "segment_id": "seg-3", "chunk_id": "chunk-3", "content": "C", "rerank_score": 0.7},
        ]
        sources = AIClient.build_sources_from_evidence(evidence)
        assert len(sources) == 3
        # citation_index is 1-based and matches evidence order
        assert sources[0]["citation_index"] == 1
        assert sources[1]["citation_index"] == 2
        assert sources[2]["citation_index"] == 3
        # source_type: segment_id present -> dify (even if chunk_id also present)
        assert sources[0]["source_type"] == "dify"
        assert sources[1]["source_type"] == "local"
        assert sources[2]["source_type"] == "dify"
        # source_id stable
        assert sources[0]["source_id"] == "seg-1"
        assert sources[1]["source_id"] == "chunk-2"
        assert sources[2]["source_id"] == "seg-3"
        # no re-sorting: order preserved
        assert [s["document"] for s in sources] == ["doc-a", "doc-b", "doc-c"]

    def test_empty_evidence_returns_empty_list(self):
        assert AIClient.build_sources_from_evidence([]) == []
        assert AIClient.build_sources_from_evidence(None) == []

    def test_backward_compatible_fields_present(self):
        """Existing frontend fields (document/section/page/score/quote) must remain."""
        evidence = [
            {
                "source_file": "formal-20-02-04",
                "segment_id": "seg-x",
                "section": "1.2.3",
                "page": 42,
                "content": "test quote",
                "rerank_score": 0.55,
            }
        ]
        s = AIClient.build_sources_from_evidence(evidence)[0]
        for field in ("document", "section", "page", "score", "quote"):
            assert field in s, f"missing backward-compatible field: {field}"
        assert s["document"] == "formal-20-02-04"
        assert s["quote"] == "test quote"

    def test_missing_fields_default_safely(self):
        evidence = [{"source_file": "minimal", "content": "min"}]
        s = AIClient.build_sources_from_evidence(evidence)[0]
        assert s["source_type"] == "local"  # no segment_id
        assert s["source_id"] is None       # no chunk_id either
        assert s["section"] == ""
        assert s["page"] == 0
        assert s["score"] == 0

    def test_non_dict_items_skipped(self):
        evidence = [{"source_file": "ok", "segment_id": "s1", "content": "x"}, "not-a-dict", None]
        sources = AIClient.build_sources_from_evidence(evidence)
        assert len(sources) == 1
        assert sources[0]["source_id"] == "s1"

    def test_api_schema_preserves_unified_source_fields(self):
        sources = AIClient.build_sources_from_evidence([
            {"source_file": "ZRDDS用户手册.pdf", "chunk_id": "chunk-1", "content": "中文证据"},
            {
                "source_file": "formal-15-04-10",
                "segment_id": "formal-segment",
                "chunk_id": "formal-chunk",
                "position": 12,
                "content": "take_next_sample removes it from the DataReader so it is no longer accessible.",
            },
        ])
        payload = ChatData(
            conversation_id="conversation-1",
            answer="answer",
            status="answered",
            sources=sources,
        ).model_dump()["sources"][1]
        assert payload["source_id"] == "formal-segment"
        assert payload["source_type"] == "dify"
        assert payload["citation_index"] == 2
        assert payload["segment_id"] == "formal-segment"
        assert payload["position"] == 12
        assert payload["document"] == "formal-15-04-10"
        assert "no longer accessible" in payload["quote"]


class TestQueryFallbackToRetrieverResources:
    """When evidence is empty, query() must still use _extract_sources (retriever_resources)."""

    def test_empty_evidence_falls_back_to_dify_sources(self, monkeypatch):
        ai = AIClient()
        fake_data = {
            "answer": "test answer",
            "metadata": {
                "retriever_resources": [
                    {
                        "document_name": "dify-doc",
                        "segment_id": "dify-seg-1",
                        "content": "dify quote",
                        "score": 0.7,
                    }
                ]
            },
        }

        async def fake_post(*args, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self): return fake_data
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        async def _run():
            return await ai.query(question="test", evidence=None)

        result = asyncio.run(_run())
        assert len(result["sources"]) == 1
        assert result["sources"][0]["document"] == "dify-doc"
        assert result["sources"][0]["source_id"] == "dify-seg-1"
        assert result["sources"][0]["source_type"] == "dify"
        assert result["sources"][0]["citation_index"] == 1

    def test_evidence_overrides_dify_retriever_resources(self, monkeypatch):
        ai = AIClient()
        fake_data = {
            "answer": "test",
            "metadata": {"retriever_resources": []},
        }

        async def fake_post(*args, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self): return fake_data
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        evidence = [
            {"source_file": "formal-15-04-10", "segment_id": "seg-core", "content": "core", "rerank_score": 0.99}
        ]

        async def _run():
            return await ai.query(question="test", evidence=evidence)

        result = asyncio.run(_run())
        assert len(result["sources"]) == 1
        assert result["sources"][0]["source_type"] == "dify"
        assert result["sources"][0]["source_id"] == "seg-core"
        assert result["sources"][0]["document"] == "formal-15-04-10"
        assert result["sources"][0]["citation_index"] == 1
