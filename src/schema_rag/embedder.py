"""Embedding model wrapper — bge-large-zh-v1.5.

Reuses the singleton pattern from the RAG movie project.
The model is loaded once and cached for the process lifetime.

Usage:
    embedder = get_embedder()
    vectors = embedder.encode(["text1", "text2"])
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from src.core.config import AppConfig


class Embedder:
    """Wrapper around sentence-transformers for bge-large-zh."""

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", normalize: bool = True):
        self._model_name = model_name
        self._normalize = normalize
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts to embeddings.

        Args:
            texts: List of text strings to embed.
            batch_size: Batch size for encoding.

        Returns:
            numpy array of shape (len(texts), dimension).
        """
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
        )
        return np.array(embeddings)

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text to an embedding vector."""
        return self.encode([text])[0]

    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        return self.model.get_sentence_embedding_dimension()


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_embedder: Embedder | None = None


def get_embedder(config: AppConfig | None = None) -> Embedder:
    """Get or create the global Embedder instance.

    Args:
        config: Optional AppConfig. If provided on first call, uses its
                embedding.model and embedding.normalize settings.

    Returns:
        The singleton Embedder instance.
    """
    global _embedder
    if _embedder is None:
        if config is not None:
            _embedder = Embedder(
                model_name=config.embedding.model,
                normalize=config.embedding.normalize,
            )
        else:
            _embedder = Embedder()
    return _embedder
