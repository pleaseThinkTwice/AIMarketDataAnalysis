"""BM25 keyword-based retriever for schema chunks.

Uses rank_bm25 + jieba tokenizer for Chinese text support.
Serves as the keyword-matching complement to the vector store.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi


class BM25Retriever:
    """BM25 keyword search over schema chunk text."""

    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunks: list[Any] = []
        self._tokenized: list[list[str]] = []

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text using jieba for Chinese + whitespace for English."""
        # jieba.cut returns generator; convert to list
        tokens = list(jieba.cut(text))
        # Also split on whitespace for English terms
        result = []
        for token in tokens:
            result.extend(token.strip().lower().split())
        return [t for t in result if t and len(t) > 1]

    def build(self, chunks: list[Any]) -> None:
        """Build the BM25 index from schema chunks.

        Args:
            chunks: List of SchemaChunk objects.
        """
        self._chunks = list(chunks)
        self._tokenized = [self._tokenize(c.text) for c in chunks]
        if self._tokenized:
            self._bm25 = BM25Okapi(self._tokenized)

    def search(self, query: str, top_k: int = 15) -> list[dict[str, Any]]:
        """Search for the top-k most relevant chunks.

        Args:
            query: Search query text.
            top_k: Number of results to return.

        Returns:
            List of dicts with chunk_id, text, chunk_type, table, column, score.
        """
        if self._bm25 is None or not self._tokenized:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)
        # Get top-k indices
        top_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            chunk = self._chunks[idx]
            results.append({
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "chunk_type": chunk.chunk_type,
                "table": chunk.table,
                "column": chunk.column,
                "score": float(scores[idx]),
            })
        return results

    def save(self, path: str | Path) -> None:
        """Persist the BM25 index to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump({
                "chunks": self._chunks,
                "tokenized": self._tokenized,
            }, fh)

    def load(self, path: str | Path) -> bool:
        """Load the BM25 index from disk. Returns True on success."""
        path = Path(path)
        if not path.exists():
            return False
        with open(path, "rb") as fh:
            data = pickle.load(fh)
        self._chunks = data["chunks"]
        self._tokenized = data["tokenized"]
        if self._tokenized:
            self._bm25 = BM25Okapi(self._tokenized)
        return True
