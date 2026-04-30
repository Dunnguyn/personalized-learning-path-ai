"""Backward-compatible import shim for hybrid recommendations."""

from backend.app.services.recommendation.candidate_retrieval import (
    HybridRecommendationService,
    ResourceRecommendationWeights,
    hybrid_recommendation_service,
)

__all__ = [
    "HybridRecommendationService",
    "ResourceRecommendationWeights",
    "hybrid_recommendation_service",
]
