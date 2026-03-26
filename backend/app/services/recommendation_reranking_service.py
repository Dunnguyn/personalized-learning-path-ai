"""Diversity-aware reranking layer for recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np


@dataclass
class ReRankingConfig:
    enabled: bool = True
    lambda_relevance: float = 0.75
    exploration_weight: float = 0.03


class RecommendationRerankingService:
    """Apply MMR-style reranking with metadata-aware diversity constraints."""

    def __init__(self, config: ReRankingConfig | None = None) -> None:
        self.config = config or ReRankingConfig()

    @staticmethod
    def _safe_vector(value: Any) -> np.ndarray | None:
        if not value:
            return None
        try:
            vector = np.array(value, dtype=float)
            if vector.size == 0:
                return None
            return vector
        except Exception:
            return None

    def _metadata_similarity(
        self, left: Dict[str, Any], right: Dict[str, Any]
    ) -> float:
        matches = 0.0
        total = 0.0
        for key in ("source", "type", "topic", "level", "pedagogy_type"):
            left_value = str(left.get(key) or "").strip().lower()
            right_value = str(right.get(key) or "").strip().lower()
            if not left_value or not right_value:
                continue
            total += 1.0
            if left_value == right_value:
                matches += 1.0
        if total == 0:
            return 0.0
        return matches / total

    def _item_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        metadata_sim = self._metadata_similarity(left, right)

        left_vector = self._safe_vector(left.get("embedding"))
        right_vector = self._safe_vector(right.get("embedding"))
        if left_vector is None or right_vector is None:
            return metadata_sim

        denominator = float(np.linalg.norm(left_vector) * np.linalg.norm(right_vector))
        if denominator <= 0:
            return metadata_sim
        semantic_sim = float(np.dot(left_vector, right_vector) / denominator)
        semantic_sim = max(0.0, min(1.0, semantic_sim))
        return 0.6 * semantic_sim + 0.4 * metadata_sim

    @staticmethod
    def _novelty_bonus(candidate: Dict[str, Any]) -> float:
        popularity = float(candidate.get("popularity", 0.0) or 0.0)
        seen_penalty = 1.0 if bool(candidate.get("is_recently_seen", False)) else 0.0
        inv_popularity = 1.0 / (1.0 + popularity)
        return max(0.0, min(1.0, inv_popularity * (1.0 - 0.35 * seen_penalty)))

    def rerank(self, candidates: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
        if not candidates:
            return {
                "items": [],
                "metadata": {"strategy": "empty", "diversity_ratio": 0.0},
            }

        top_limit = max(1, limit)
        sorted_candidates = sorted(
            candidates,
            key=lambda item: float(item.get("final_base_score", 0.0)),
            reverse=True,
        )

        if not self.config.enabled:
            return {
                "items": sorted_candidates[:top_limit],
                "metadata": {"strategy": "disabled", "diversity_ratio": 0.0},
            }

        selected: List[Dict[str, Any]] = []
        remaining = list(sorted_candidates)

        while remaining and len(selected) < top_limit:
            best_idx = 0
            best_score = float("-inf")

            for idx, candidate in enumerate(remaining):
                relevance = float(candidate.get("final_base_score", 0.0) or 0.0)
                novelty = self._novelty_bonus(candidate)
                exploration = self.config.exploration_weight * novelty

                max_similarity = 0.0
                if selected:
                    max_similarity = max(
                        self._item_similarity(candidate, chosen) for chosen in selected
                    )

                mmr_score = (
                    self.config.lambda_relevance * relevance
                    - (1.0 - self.config.lambda_relevance) * max_similarity
                    + exploration
                )

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx

            chosen = remaining.pop(best_idx)
            chosen["rerank_score"] = round(best_score, 6)
            selected.append(chosen)

        distinct_sources = {
            str(item.get("source") or "") for item in selected if item.get("source")
        }
        distinct_topics = {
            str(item.get("topic") or "") for item in selected if item.get("topic")
        }
        distinct_formats = {
            str(item.get("type") or "") for item in selected if item.get("type")
        }

        denominator = max(len(selected), 1)
        diversity_ratio = min(
            1.0,
            (len(distinct_sources) + len(distinct_topics) + len(distinct_formats))
            / (3.0 * denominator),
        )

        return {
            "items": selected,
            "metadata": {
                "strategy": "mmr",
                "lambda_relevance": self.config.lambda_relevance,
                "exploration_weight": self.config.exploration_weight,
                "distinct_sources": len(distinct_sources),
                "distinct_topics": len(distinct_topics),
                "distinct_formats": len(distinct_formats),
                "diversity_ratio": round(diversity_ratio, 4),
            },
        }
