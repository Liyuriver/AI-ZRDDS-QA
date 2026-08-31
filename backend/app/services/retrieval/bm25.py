"""BM25 index wrapper."""

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from rank_bm25 import BM25Okapi

from app.services.retrieval.tokenizer import tokenize


class BM25Index:
    def __init__(self) -> None:
        self._chunks: List[Mapping[str, Any]] = []
        self._index: BM25Okapi | None = None

    def build_index(self, chunks: Iterable[Mapping[str, Any]]) -> "BM25Index":
        self._chunks = list(chunks)
        self._index = BM25Okapi([tokenize(chunk.get("content", "")) for chunk in self._chunks])
        return self

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not query or top_k <= 0 or not self._chunks or self._index is None:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._index.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda pair: (-float(pair[1]), pair[0]))
        # A zero score means that none of the query tokens occurs in the corpus.
        # Do not return arbitrary zero-score chunks as false evidence.
        return [dict(self._chunks[index], score=float(score))
                for index, score in ranked if float(score) > 0][:top_k]
