"""Reciprocal Rank Fusion (RRF) for combining vector + BM25 results.

RRF merges ranked lists from different retrieval sources by scoring each
document as sum(1 / (k + rank_i)) across all sources. This avoids the
problem of comparing raw scores from different score distributions.

Reused from the RAG movie recommendation project (identical algorithm).
"""

from __future__ import annotations

from typing import Any


def rrf_fuse(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    k: int = 60,
    top_k: int = 15,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list[dict[str, Any]]:
    """Fuse two ranked result lists using weighted Reciprocal Rank Fusion.

    Args:
        vector_results: Results from vector search, ranked (best first).
        bm25_results: Results from BM25 search, ranked (best first).
        k: RRF constant (typically 60). Higher = smoother.
        top_k: Number of fused results to return.
        vector_weight: Weight for vector source (default 0.6).
        bm25_weight: Weight for BM25 source (default 0.4).

    Returns:
        Top-k fused results with rrf_score added to each dict.
    """
    # Build chunk_id → original item mapping
    item_map: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}

    # Vector scores
    for rank, item in enumerate(vector_results):
        cid = item.get("chunk_id", "")
        if cid not in item_map:
            item_map[cid] = dict(item)
        scores[cid] = scores.get(cid, 0.0) + vector_weight / (k + rank + 1)

    # BM25 scores
    for rank, item in enumerate(bm25_results):
        cid = item.get("chunk_id", "")
        if cid not in item_map:
            item_map[cid] = dict(item)
        scores[cid] = scores.get(cid, 0.0) + bm25_weight / (k + rank + 1)

    # Sort by RRF score descending
    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]

    result = []
    for cid in sorted_ids:
        item = dict(item_map[cid])
        item["rrf_score"] = scores[cid]
        result.append(item)

    return result
