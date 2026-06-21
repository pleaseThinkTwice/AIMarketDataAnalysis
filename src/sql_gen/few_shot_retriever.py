"""Dynamic few-shot exemplar retrieval.

Embeds the current task description and retrieves the Top-3 most
semantically similar exemplars from the few-shot library.

Why dynamic over static:
    - Different SQL patterns (aggregation, window, subquery, UNION)
      require different exemplars.
    - Fixed few-shot either over-generalizes or over-fits to one pattern.
    - Dynamic retrieval gives the LLM pattern-matched examples to imitate.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.core.schemas import FewShotExample
from src.schema_rag.embedder import get_embedder
from src.sql_gen.few_shot_store import FewShotStore


class FewShotRetriever:
    """Retrieves task-similar few-shot exemplars via embedding similarity."""

    def __init__(
        self,
        store: FewShotStore | None = None,
        top_k: int = 3,
    ) -> None:
        self._store = store or FewShotStore()
        self._top_k = top_k
        self._embedder = get_embedder()

    def retrieve(self, task_description: str) -> list[FewShotExample]:
        """Retrieve the top-k most similar exemplars.

        Args:
            task_description: Natural language task description.

        Returns:
            List of FewShotExample, ordered by similarity (most similar first).
        """
        examples = self._store.list_all()
        if not examples:
            return []

        # Seed with defaults if empty
        if len(examples) == 0:
            self._store.seed_with_defaults()
            examples = self._store.list_all()

        if len(examples) <= self._top_k:
            return examples

        # Embed query and all exemplar task texts
        query_vec = self._embedder.encode_single(task_description)
        task_texts = [e.task_text for e in examples]
        example_vecs = self._embedder.encode(task_texts)

        # Cosine similarity
        similarities = np.dot(example_vecs, query_vec)

        # Top-k indices
        top_indices = np.argsort(similarities)[::-1][:self._top_k]

        return [examples[i] for i in top_indices]
