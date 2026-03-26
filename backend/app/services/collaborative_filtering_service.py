"""Implicit-feedback collaborative filtering for recommendation boost."""

from __future__ import annotations

import math
from typing import Dict, List

from backend.app.repositories.recommendation_repository import RecommendationRepository


class CollaborativeFilteringService:
    """Compute lightweight collaborative scores from event logs."""

    def __init__(self, repository: RecommendationRepository) -> None:
        self.repository = repository

    @staticmethod
    def _cosine_similarity(left: Dict[str, float], right: Dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        overlap_keys = set(left).intersection(right)
        if not overlap_keys:
            return 0.0

        dot = sum(left[item] * right[item] for item in overlap_keys)
        norm_left = math.sqrt(sum(value * value for value in left.values()))
        norm_right = math.sqrt(sum(value * value for value in right.values()))
        if norm_left == 0.0 or norm_right == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_left * norm_right)))

    @staticmethod
    def _normalize(values: Dict[str, float]) -> Dict[str, float]:
        if not values:
            return {}
        max_score = max(values.values())
        min_score = min(values.values())
        if max_score <= min_score:
            return {key: 1.0 for key in values}
        span = max_score - min_score
        return {key: (value - min_score) / span for key, value in values.items()}

    def score_candidates(
        self, *, user_id: str | int, candidate_keys: List[str]
    ) -> Dict[str, float]:
        """Return collaborative scores in range [0, 1] for candidate resources."""
        unique_candidates = [str(item) for item in candidate_keys if item is not None]
        if not unique_candidates:
            return {}

        target_vector = self.repository.get_user_resource_interactions(user_id)
        if not target_vector:
            return {}

        peers = self.repository.get_peers_for_resources(
            resource_keys=unique_candidates,
            exclude_user_id=user_id,
        )
        if not peers:
            return {}

        peer_similarities: Dict[str, float] = {}
        for peer_id, peer_vector in peers.items():
            similarity = self._cosine_similarity(target_vector, peer_vector)
            if similarity >= 0.05:
                peer_similarities[peer_id] = similarity

        if not peer_similarities:
            return {}

        raw_scores: Dict[str, float] = {key: 0.0 for key in unique_candidates}
        norm_denominators: Dict[str, float] = {key: 0.0 for key in unique_candidates}

        for peer_id, similarity in peer_similarities.items():
            peer_vector = peers.get(peer_id, {})
            for resource_key in unique_candidates:
                value = float(peer_vector.get(resource_key, 0.0))
                if value <= 0:
                    continue
                raw_scores[resource_key] += similarity * value
                norm_denominators[resource_key] += similarity

        for resource_key, denominator in norm_denominators.items():
            if denominator > 0:
                raw_scores[resource_key] /= denominator

        return self._normalize({k: v for k, v in raw_scores.items() if v > 0})
