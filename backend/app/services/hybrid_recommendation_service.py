"""Hybrid recommendation service: semantic + learner state + CF + reranking."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
from typing import Any, Dict, List, Tuple

import numpy as np

from backend.app.services.embedding_service import embed_text
from backend.app.repositories.recommendation_repository import RecommendationRepository
from backend.app.services.collaborative_filtering_service import (
    CollaborativeFilteringService,
)
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)


@dataclass
class HybridWeights:
    semantic_score: float = float(os.getenv("REC_W_SEMANTIC", "0.30"))
    mastery_fit_score: float = float(os.getenv("REC_W_MASTERY", "0.18"))
    confidence_fit_score: float = float(os.getenv("REC_W_CONFIDENCE", "0.08"))
    goal_fit_score: float = float(os.getenv("REC_W_GOAL", "0.10"))
    difficulty_fit_score: float = float(os.getenv("REC_W_DIFFICULTY", "0.10"))
    collaborative_score: float = float(os.getenv("REC_W_COLLAB", "0.12"))
    pedagogical_score: float = float(os.getenv("REC_W_PEDAGOGY", "0.05"))
    format_preference_score: float = float(os.getenv("REC_W_FORMAT_PREF", "0.04"))
    novelty_score: float = float(os.getenv("REC_W_NOVELTY", "0.03"))

    def normalize(self) -> "HybridWeights":
        values = [
            self.semantic_score,
            self.mastery_fit_score,
            self.confidence_fit_score,
            self.goal_fit_score,
            self.difficulty_fit_score,
            self.collaborative_score,
            self.pedagogical_score,
            self.format_preference_score,
            self.novelty_score,
        ]
        total = sum(max(0.0, value) for value in values)
        if total <= 0:
            return HybridWeights()

        return HybridWeights(
            semantic_score=self.semantic_score / total,
            mastery_fit_score=self.mastery_fit_score / total,
            confidence_fit_score=self.confidence_fit_score / total,
            goal_fit_score=self.goal_fit_score / total,
            difficulty_fit_score=self.difficulty_fit_score / total,
            collaborative_score=self.collaborative_score / total,
            pedagogical_score=self.pedagogical_score / total,
            format_preference_score=self.format_preference_score / total,
            novelty_score=self.novelty_score / total,
        )


class HybridRecommendationService:
    """Build recommendations with hybrid scoring and diversity-aware reranking."""

    _LEVEL_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}

    def __init__(self) -> None:
        self.repository = RecommendationRepository()
        self.collaborative = CollaborativeFilteringService(self.repository)
        self.reranker = RecommendationRerankingService(
            ReRankingConfig(
                enabled=os.getenv("REC_RERANK_ENABLED", "true").lower() == "true",
                lambda_relevance=float(os.getenv("REC_RERANK_LAMBDA", "0.75")),
                exploration_weight=float(os.getenv("REC_EXPLORATION_WEIGHT", "0.03")),
            )
        )
        self.weights = HybridWeights().normalize()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _goal_tokens(goal: str) -> List[str]:
        return [
            token.lower() for token in re.findall(r"\w+", goal or "") if len(token) >= 3
        ]

    @staticmethod
    def _cosine(left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            return 0.0
        value = float(np.dot(left, right) / denominator)
        return max(0.0, min(1.0, value))

    def _semantic_score(
        self, goal_vector: np.ndarray | None, resource: Dict[str, Any]
    ) -> float:
        if goal_vector is None:
            return 0.0
        vector = resource.get("embedding")
        if not vector:
            return 0.0
        try:
            resource_vector = np.array(vector, dtype=float)
        except Exception:
            return 0.0
        return self._cosine(goal_vector, resource_vector)

    def _goal_fit_score(
        self, goal_tokens: List[str], resource: Dict[str, Any]
    ) -> float:
        if not goal_tokens:
            return 0.0
        text = " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str((resource.get("metadata") or {}).get("summary") or ""),
            ]
        ).lower()
        if not text.strip():
            return 0.0
        matched = sum(1 for token in goal_tokens if token in text)
        return min(1.0, matched / max(len(goal_tokens), 1))

    def _difficulty_fit_score(self, learner_level: str, resource_level: str) -> float:
        learner_rank = self._LEVEL_ORDER.get(str(learner_level).lower(), 1)
        resource_rank = self._LEVEL_ORDER.get(str(resource_level).lower(), learner_rank)
        distance = abs(learner_rank - resource_rank)
        if distance == 0:
            return 1.0
        if distance == 1:
            return 0.6
        return 0.25

    def _pedagogical_score(
        self, learner_level: str, pedagogy_type: str | None
    ) -> float:
        pedagogy = str(pedagogy_type or "").lower()
        if not pedagogy:
            return 0.5

        table = {
            "beginner": {"video": 0.95, "text": 0.75, "quiz": 0.55, "exercise": 0.6},
            "intermediate": {"video": 0.7, "text": 0.85, "quiz": 0.75, "exercise": 0.8},
            "advanced": {"video": 0.55, "text": 0.9, "quiz": 0.9, "exercise": 0.95},
        }
        return table.get(str(learner_level).lower(), table["intermediate"]).get(
            pedagogy, 0.5
        )

    @staticmethod
    def _novelty_score(popularity: float, recently_seen: bool) -> float:
        base = 1.0 / (1.0 + max(0.0, popularity))
        if recently_seen:
            base *= 0.5
        return max(0.0, min(1.0, base))

    def _format_preference_score(
        self, user_pref: Dict[str, float], resource: Dict[str, Any]
    ) -> float:
        if not user_pref:
            return 0.5
        fmt = str(resource.get("type") or resource.get("source") or "").lower()
        return max(0.0, min(1.0, float(user_pref.get(fmt, 0.15))))

    @staticmethod
    def _explain(component: Dict[str, float]) -> str:
        ranked = sorted(component.items(), key=lambda item: item[1], reverse=True)
        top = [name for name, score in ranked if score >= 0.5][:2]
        if not top:
            return "Recommended by blended relevance and learner-state match"
        return "Strong on " + ", ".join(top).replace("_", " ")

    def _compute_base_score(self, components: Dict[str, float]) -> float:
        w = self.weights
        score = (
            w.semantic_score * components["semantic_score"]
            + w.mastery_fit_score * components["mastery_fit_score"]
            + w.confidence_fit_score * components["confidence_fit_score"]
            + w.goal_fit_score * components["goal_fit_score"]
            + w.difficulty_fit_score * components["difficulty_fit_score"]
            + w.collaborative_score * components["collaborative_score"]
            + w.pedagogical_score * components["pedagogical_score"]
            + w.format_preference_score * components["format_preference_score"]
            + w.novelty_score * components["novelty_score"]
        )
        return max(0.0, min(1.0, score))

    def recommend_resources(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
    ) -> Dict[str, Any]:
        progress_rows = self.repository.get_user_progress(user_id)
        mastery_map = {
            int(item.get("concept_id", 0)): self._safe_float(item.get("mastery"), 0.0)
            for item in progress_rows
        }
        confidence_map = {
            int(item.get("concept_id", 0)): self._safe_float(
                item.get("confidence"), 0.0
            )
            for item in progress_rows
        }

        goal_concepts = self.repository.find_goal_concepts(goal=goal, limit=60)
        completed = [
            item["concept_id"]
            for item in goal_concepts
            if mastery_map.get(int(item["concept_id"]), 0.0) >= 0.8
        ]
        next_concepts = [
            item
            for item in goal_concepts
            if int(item["concept_id"]) not in set(completed)
        ]

        if not goal_concepts:
            return {
                "recommended": [],
                "completed_concepts": 0,
                "total_concepts": 0,
                "progress_percentage": 0.0,
                "reranking": {"strategy": "none", "diversity_ratio": 0.0},
            }

        candidate_concept_ids = [
            int(item["concept_id"]) for item in (next_concepts or goal_concepts)[:10]
        ]
        fallback_level = {
            "beginner": "intermediate",
            "intermediate": "advanced",
            "advanced": "advanced",
        }
        preferred_levels = [level, fallback_level.get(level, level)]

        resources = self.repository.find_resources_for_concepts(
            concept_ids=candidate_concept_ids,
            preferred_levels=preferred_levels,
            limit=max(limit * 4, 20),
        )

        if not resources:
            return {
                "recommended": [],
                "completed_concepts": len(completed),
                "total_concepts": len(goal_concepts),
                "progress_percentage": (len(completed) / len(goal_concepts) * 100.0),
                "reranking": {"strategy": "none", "diversity_ratio": 0.0},
            }

        goal_vector = None
        try:
            goal_vector = np.array(embed_text(goal), dtype=float)
        except Exception:
            goal_vector = None

        goal_tokens = self._goal_tokens(goal)
        user_pref = self.repository.get_user_format_preference(user_id)
        candidate_keys = [self.repository.get_resource_key(item) for item in resources]
        collaborative_scores = self.collaborative.score_candidates(
            user_id=user_id, candidate_keys=candidate_keys
        )
        popularity_map = self.repository.get_resource_popularity(candidate_keys)
        recently_seen = set(
            self.repository.get_recently_seen_resources(user_id=user_id, limit=30)
        )

        scored_items: List[Dict[str, Any]] = []
        for resource in resources:
            resource_key = self.repository.get_resource_key(resource)
            concept_id = int(resource.get("concept_id") or 0)
            mastery = max(0.0, min(1.0, mastery_map.get(concept_id, 0.0)))
            confidence = max(0.0, min(1.0, confidence_map.get(concept_id, 0.0)))

            components = {
                "semantic_score": self._semantic_score(goal_vector, resource),
                "mastery_fit_score": max(0.0, min(1.0, 1.0 - mastery)),
                "confidence_fit_score": max(0.0, min(1.0, 1.0 - confidence)),
                "goal_fit_score": self._goal_fit_score(goal_tokens, resource),
                "difficulty_fit_score": self._difficulty_fit_score(
                    level, str(resource.get("level") or level)
                ),
                "collaborative_score": collaborative_scores.get(resource_key, 0.0),
                "pedagogical_score": self._pedagogical_score(
                    level,
                    str(
                        (resource.get("metadata") or {}).get("pedagogy_type")
                        or resource.get("pedagogy_type")
                        or ""
                    ),
                ),
                "format_preference_score": self._format_preference_score(
                    user_pref, resource
                ),
                "novelty_score": self._novelty_score(
                    popularity_map.get(resource_key, 0.0), resource_key in recently_seen
                ),
            }
            base_score = self._compute_base_score(components)

            scored_items.append(
                {
                    "resource": resource,
                    "resource_key": resource_key,
                    "components": {
                        key: round(value, 6) for key, value in components.items()
                    },
                    "final_base_score": round(base_score, 6),
                    "popularity": float(popularity_map.get(resource_key, 0.0)),
                    "is_recently_seen": resource_key in recently_seen,
                    "source": resource.get("source"),
                    "type": resource.get("type"),
                    "topic": resource.get("topic"),
                    "level": resource.get("level"),
                    "embedding": resource.get("embedding"),
                    "pedagogy_type": (resource.get("metadata") or {}).get(
                        "pedagogy_type"
                    )
                    or resource.get("pedagogy_type"),
                }
            )

        scored_items.sort(key=lambda item: item["final_base_score"], reverse=True)
        selected_pool = scored_items[: max(limit * 3, limit)]

        reranking_result = (
            self.reranker.rerank(selected_pool, limit=limit)
            if enable_reranking
            else {
                "items": selected_pool[:limit],
                "metadata": {"strategy": "disabled", "diversity_ratio": 0.0},
            }
        )

        recommended = []
        for rank, item in enumerate(reranking_result["items"], start=1):
            resource = item["resource"]
            component_scores = item["components"]
            final_score = self._safe_float(
                item.get("rerank_score"), item.get("final_base_score", 0.0)
            )
            reason = self._explain(component_scores)

            resource_identifier = resource.get("resource_id")
            if resource_identifier is None:
                # Keep backward compatibility with existing response contract expecting int.
                # Use deterministic hashed int from object id if legacy numeric id is unavailable.
                resource_identifier = abs(hash(str(resource.get("_id")))) % 10_000_000

            recommended.append(
                {
                    "resource_id": int(resource_identifier),
                    "title": str(resource.get("title") or ""),
                    "source": str(resource.get("source") or "unknown"),
                    "level": str(resource.get("level") or level),
                    "topic": str(resource.get("topic") or ""),
                    "url": (resource.get("metadata") or {}).get("url")
                    or resource.get("url"),
                    "reason": reason,
                    "relevance_score": round(max(0.0, min(1.0, final_score)), 4),
                    "score_breakdown": component_scores,
                    "rank_position": rank,
                }
            )

        progress_percentage = (
            (len(completed) / len(goal_concepts) * 100.0) if goal_concepts else 0.0
        )

        return {
            "recommended": recommended,
            "completed_concepts": len(completed),
            "total_concepts": len(goal_concepts),
            "progress_percentage": round(progress_percentage, 2),
            "reranking": reranking_result.get("metadata", {}),
        }

    def recommendation_debug_snapshot(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
    ) -> Dict[str, Any]:
        """Return debug payload for tuning hybrid/CF/reranking signals."""
        result = self.recommend_resources(
            user_id=user_id,
            goal=goal,
            level=level,
            limit=limit,
            enable_reranking=enable_reranking,
        )

        recommended = result.get("recommended", [])
        candidate_keys = [
            str(item.get("resource_id"))
            for item in recommended
            if item.get("resource_id") is not None
        ]

        collaborative_scores = self.collaborative.score_candidates(
            user_id=user_id, candidate_keys=candidate_keys
        )
        popularity_map = self.repository.get_resource_popularity(candidate_keys)
        user_vector = self.repository.get_user_resource_interactions(user_id)

        debug_items: List[Dict[str, Any]] = []
        for item in recommended:
            resource_id = item.get("resource_id")
            resource_key = str(resource_id) if resource_id is not None else ""
            debug_items.append(
                {
                    "resource_id": resource_id,
                    "title": item.get("title"),
                    "relevance_score": item.get("relevance_score"),
                    "rank_position": item.get("rank_position"),
                    "score_breakdown": item.get("score_breakdown", {}),
                    "collaborative_debug": {
                        "normalized_collaborative_score": round(
                            float(collaborative_scores.get(resource_key, 0.0)), 6
                        ),
                        "user_interaction_weight": round(
                            float(user_vector.get(resource_key, 0.0)), 6
                        ),
                        "popularity_weight": round(
                            float(popularity_map.get(resource_key, 0.0)), 6
                        ),
                    },
                }
            )

        return {
            "weights": {
                "semantic_score": round(self.weights.semantic_score, 6),
                "mastery_fit_score": round(self.weights.mastery_fit_score, 6),
                "confidence_fit_score": round(self.weights.confidence_fit_score, 6),
                "goal_fit_score": round(self.weights.goal_fit_score, 6),
                "difficulty_fit_score": round(self.weights.difficulty_fit_score, 6),
                "collaborative_score": round(self.weights.collaborative_score, 6),
                "pedagogical_score": round(self.weights.pedagogical_score, 6),
                "format_preference_score": round(
                    self.weights.format_preference_score, 6
                ),
                "novelty_score": round(self.weights.novelty_score, 6),
            },
            "input": {
                "user_id": str(user_id),
                "goal": goal,
                "level": level,
                "limit": limit,
                "enable_reranking": enable_reranking,
            },
            "user_signal_summary": {
                "interaction_vector_size": len(user_vector),
                "top_interactions": sorted(
                    [
                        {"resource_key": key, "weight": round(float(value), 6)}
                        for key, value in user_vector.items()
                    ],
                    key=lambda row: row["weight"],
                    reverse=True,
                )[:10],
            },
            "reranking": result.get("reranking", {}),
            "recommended_debug": debug_items,
        }


hybrid_recommendation_service = HybridRecommendationService()
