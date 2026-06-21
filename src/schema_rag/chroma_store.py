"""ChromaDB vector store for schema chunks.

Manages a persistent ChromaDB collection storing embedded schema chunks.
Supports build (from chunks), query (by embedding), and persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
import numpy as np


class SchemaChromaStore:
    """ChromaDB-backed vector store for schema RAG."""

    COLLECTION_NAME = "schema_chunks"

    def __init__(self, persist_dir: str | Path = "data/indexes"):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
        )
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            # Delete existing if we want to rebuild (handled by caller)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def build(self, chunks: list[Any], embeddings: np.ndarray) -> None:
        """Build (or rebuild) the index from chunks and their embeddings.

        Args:
            chunks: List of SchemaChunk objects.
            embeddings: numpy array of shape (len(chunks), dim).
        """
        # Delete and recreate for a clean rebuild
        try:
            self._client.delete_collection(self.COLLECTION_NAME)
        except Exception:
            pass

        self._collection = self._client.create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {"chunk_type": c.chunk_type, "table": c.table, "column": c.column}
            for c in chunks
        ]

        # Batch insert
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            end = min(i + batch_size, len(ids))
            self._collection.add(
                ids=ids[i:end],
                documents=documents[i:end],
                metadatas=metadatas[i:end],
                embeddings=embeddings[i:end].tolist(),
            )

    def query(self, query_embedding: np.ndarray, top_k: int = 15) -> list[dict[str, Any]]:
        """Query the index for the top-k most similar chunks.

        Args:
            query_embedding: A single embedding vector of shape (dim,).
            top_k: Number of chunks to retrieve.

        Returns:
            List of dicts with keys: chunk_id, text, chunk_type, table, column, distance.
        """
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
        )

        chunks = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "chunk_type": results["metadatas"][0][i].get("chunk_type", "") if results["metadatas"] else "",
                    "table": results["metadatas"][0][i].get("table", "") if results["metadatas"] else "",
                    "column": results["metadatas"][0][i].get("column", "") if results["metadatas"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                })
        return chunks

    def count(self) -> int:
        """Return the number of chunks in the collection."""
        try:
            return self.collection.count()
        except Exception:
            return 0
