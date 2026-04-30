"""Recommendation reranking helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def rerank_scored_items(
    service: Any,
    *,
    scored_items: List[Dict[str, Any]],
    limit: int,
    enable_reranking: bool,
) -> Dict[str, Any]:
    selected_pool = scored_items[: max(limit * 3, limit)]
    if enable_reranking:
        return service.reranker.rerank(selected_pool, limit=limit)
    return {
        "items": selected_pool[:limit],
        "metadata": {"strategy": "disabled", "diversity_ratio": 0.0},
    }
