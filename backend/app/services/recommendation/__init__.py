"""Recommendation package.

Keep this module lightweight. Repository modules import helper submodules from this
package during application startup; eager-importing candidate retrieval here creates
a circular import back into the repository layer.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name in {
        "HybridRecommendationService",
        "ResourceRecommendationWeights",
        "hybrid_recommendation_service",
    }:
        from .candidate_retrieval import (
            HybridRecommendationService,
            ResourceRecommendationWeights,
            hybrid_recommendation_service,
        )

        values = {
            "HybridRecommendationService": HybridRecommendationService,
            "ResourceRecommendationWeights": ResourceRecommendationWeights,
            "hybrid_recommendation_service": hybrid_recommendation_service,
        }
        return values[name]
    raise AttributeError(name)

__all__ = [
    "HybridRecommendationService",
    "ResourceRecommendationWeights",
    "hybrid_recommendation_service",
]
