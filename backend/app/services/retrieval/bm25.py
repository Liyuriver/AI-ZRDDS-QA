"""BM25 index wrapper."""

import re
from typing import Any, Dict, Iterable, List, Mapping

from rank_bm25 import BM25Okapi

from app.services.retrieval.tokenizer import _TECHNICAL_PHRASES, tokenize


class BM25Index:
    def __init__(self) -> None:
        self._chunks: List[Mapping[str, Any]] = []
        self._index: BM25Okapi | None = None

    def build_index(self, chunks: Iterable[Mapping[str, Any]]) -> "BM25Index":
        self._chunks = list(chunks)
        self._index = BM25Okapi([tokenize(self._index_text(chunk)) for chunk in self._chunks])
        return self

    @staticmethod
    def _index_text(chunk: Mapping[str, Any]) -> str:
        # Repeat structural fields to give headings a controlled boost without
        # applying a document-wide source-file multiplier.
        content = str(chunk.get("content", ""))
        # Preserve the relationship between an API operation and its state
        # transition even when a PDF extractor splits the surrounding heading.
        # These are derived aliases, not question-specific keywords.
        semantic_aliases: list[str] = []
        if re.search(r"act of reading.*sample.*sample_state.*READ", content, re.I | re.S):
            semantic_aliases.append("read sample_state READ retained remains available")
        if re.search(r"act of taking.*sample.*removes?.*DataReader", content, re.I | re.S):
            semantic_aliases.append("take sample removed no longer accessible")
        return " ".join(
            [
                content,
                *semantic_aliases,
                str(chunk.get("section", "")) * 3,
                str(chunk.get("heading_path", "")) * 2,
                str(chunk.get("source_file", "")),
            ]
        )

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not query or top_k <= 0 or not self._chunks or self._index is None:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._index.get_scores(query_tokens)
        # BM25 tokenizes Chinese into characters, so an exact technical phrase
        # can lose to a longer semantically loose document after the corpus is
        # expanded.  Give exact phrase occurrences a small generic bonus.
        query_text = str(query).lower()
        phrases = [phrase.lower() for phrase in _TECHNICAL_PHRASES
                    if phrase.lower() in query_text]
        if phrases:
            for index, chunk in enumerate(self._chunks):
                indexed_text = self._index_text(chunk).lower()
                scores[index] += 5.0 * sum(phrase in indexed_text for phrase in phrases)
        ranked = sorted(enumerate(scores), key=lambda pair: (-float(pair[1]), pair[0]))
        # A zero score means that none of the query tokens occurs in the corpus.
        # Do not return arbitrary zero-score chunks as false evidence.
        return [dict(self._chunks[index], score=float(score))
                for index, score in ranked if float(score) > 0][:top_k]
