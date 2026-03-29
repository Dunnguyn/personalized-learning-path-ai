"""Adaptive resource recommendation service with learner-state aware scoring."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Sequence

import numpy as np

from backend.app.repositories.recommendation_repository import RecommendationRepository
from backend.app.services.collaborative_filtering_service import (
    CollaborativeFilteringService,
)
from backend.app.services.embedding_service import embed_text
from backend.app.services.expected_learning_gain_service import (
    expected_learning_gain_service,
)
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.recommendation_explanation_service import (
    recommendation_explanation_service,
)
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)
from backend.app.services.resource_quality_service import resource_quality_service


@dataclass(frozen=True)
class ResourceRecommendationWeights:
    semantic_match: float = 0.20
    concept_gap_fit: float = 0.15
    difficulty_fit: float = 0.10
    goal_fit: float = 0.10
    collaborative_score: float = 0.10
    pedagogical_fit: float = 0.08
    format_fit: float = 0.07
    engagement_fit: float = 0.08
    quality_score: float = 0.07
    expected_learning_gain: float = 0.10
    fatigue_penalty: float = 0.05
    redundancy_penalty: float = 0.05


class HybridRecommendationService:
    """Build top-level resource recommendations for multiple adaptive modes."""

    _LEVEL_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}
    _MODE_OVERRIDES: Dict[str, Dict[str, float]] = {
        "continue_learning": {
            "engagement_fit": 0.11,
            "expected_learning_gain": 0.08,
            "fatigue_penalty": 0.03,
        },
        "reinforce_weaknesses": {
            "concept_gap_fit": 0.19,
            "expected_learning_gain": 0.13,
            "quality_score": 0.08,
        },
        "learn_new": {
            "semantic_match": 0.18,
            "goal_fit": 0.13,
            "difficulty_fit": 0.12,
            "redundancy_penalty": 0.06,
        },
        "quick_review": {
            "engagement_fit": 0.10,
            "format_fit": 0.09,
            "fatigue_penalty": 0.07,
            "redundancy_penalty": 0.04,
        },
    }

    def __init__(self) -> None:
        self.repository = RecommendationRepository()
        self.collaborative = CollaborativeFilteringService(self.repository)
        self.reranker = RecommendationRerankingService(
            ReRankingConfig(enabled=True, lambda_relevance=0.76, exploration_weight=0.03)
        )
        self.learner_state_service = learner_state_service
        self.resource_quality_service = resource_quality_service
        self.expected_learning_gain_service = expected_learning_gain_service
        self.explanation_service = recommendation_explanation_service
        self.explanation_collection = self.repository.db["recommendation_explanations"]
        self.explanation_collection.create_index([("user_id", 1), ("resource_key", 1), ("mode", 1)])

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _goal_tokens(goal: str) -> List[str]:
        return [token.lower() for token in __import__("re").findall(r"\w+", goal or "") if len(token) >= 3]

    @staticmethod
    def _cosine(left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            return 0.0
        return HybridRecommendationService._clamp(float(np.dot(left, right) / denominator))

    def _weights_for_mode(self, mode: str) -> ResourceRecommendationWeights:
        weights = ResourceRecommendationWeights()
        overrides = self._MODE_OVERRIDES.get(mode, {})
        for field, value in overrides.items():
            weights = replace(weights, **{field: value})
        return weights

    def _semantic_match(self, goal_vector: np.ndarray | None, resource: Dict[str, Any]) -> float:
        vector = resource.get("embedding")
        if goal_vector is None or not vector:
            return 0.0
        try:
            return self._cosine(goal_vector, np.array(vector, dtype=float))
        except Exception:
            return 0.0

    def _goal_fit(self, goal_tokens: Sequence[str], resource: Dict[str, Any]) -> float:
        if not goal_tokens:
            return 0.0
        text = " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str((resource.get("metadata") or {}).get("summary") or ""),
            ]
        ).lower()
        matched = sum(1 for token in goal_tokens if token in text)
        return self._clamp(matched / max(len(goal_tokens), 1))

    def _difficulty_fit(self, learner_level: str, resource_level: str) -> float:
        learner_rank = self._LEVEL_ORDER.get(str(learner_level).lower(), 1)
        resource_rank = self._LEVEL_ORDER.get(str(resource_level).lower(), learner_rank)
        distance = abs(learner_rank - resource_rank)
        if distance == 0:
            return 1.0
        if distance == 1:
            return 0.68
        return 0.32

    def _pedagogical_fit(self, learner_level: str, pedagogy_type: str | None, mode: str) -> float:
        pedagogy = str(pedagogy_type or "").lower()
        table = {
            "beginner": {"video": 0.92, "text": 0.74, "quiz": 0.56, "exercise": 0.64},
            "intermediate": {"video": 0.7, "text": 0.84, "quiz": 0.76, "exercise": 0.82},
            "advanced": {"video": 0.58, "text": 0.88, "quiz": 0.92, "exercise": 0.96},
        }
        base = table.get(str(learner_level).lower(), table["intermediate"]).get(pedagogy, 0.52)
        if mode == "quick_review" and pedagogy in {"quiz", "video"}:
            return self._clamp(base + 0.12)
        if mode == "continue_learning" and pedagogy in {"text", "exercise"}:
            return self._clamp(base + 0.08)
        return self._clamp(base)

    def _format_fit(self, user_pref: Dict[str, float], resource: Dict[str, Any], mode: str) -> float:
        fmt = str(resource.get("type") or resource.get("source") or "").lower()
        base = self._clamp(float(user_pref.get(fmt, 0.45))) if user_pref else 0.52
        if mode == "quick_review" and fmt in {"pdf", "text"}:
            return self._clamp(base + 0.08)
        return base

    def _engagement_fit(self, quality: Dict[str, Any], mode: str) -> float:
        engagement = self._safe_float(quality.get("engagement_rate"), 0.45)
        completion = self._safe_float(quality.get("avg_completion_rate"), 0.4)
        helpfulness = self._safe_float(quality.get("avg_helpfulness"), 0.6)
        base = 0.45 * engagement + 0.30 * completion + 0.25 * helpfulness
        if mode == "continue_learning":
            base += 0.05 * completion
        return self._clamp(base)

    def _concept_gap_fit(
        self,
        *,
        mastery: float,
        confidence: float,
        focus_concepts: Sequence[str],
        resource: Dict[str, Any],
    ) -> float:
        topic = str(resource.get("topic") or "").lower()
        metadata = resource.get("metadata") or {}
        concepts = metadata.get("primary_concepts") or metadata.get("covered_concepts") or []
        concept_text = " ".join([topic, *(str(item).lower() for item in concepts if item)])
        focus_bonus = 0.0
        if any(str(concept).lower() in concept_text for concept in focus_concepts):
            focus_bonus = 0.18
        gap = 1.0 - ((mastery + confidence) / 2.0)
        return self._clamp(0.82 * gap + focus_bonus)

    def _expected_learning_gain(
        self,
        *,
        resource_key: str,
        concept_id: int | str | None,
        mastery: float,
        confidence: float,
        quality: Dict[str, Any],
        concept_gap_fit: float,
        mode: str,
    ) -> float:
        mastery_gap = 1.0 - mastery
        confidence_gap = 1.0 - confidence
        gain_payload = self.expected_learning_gain_service.get_expected_gain(
            resource_id=str(resource_key),
            concept_id=str(concept_id) if concept_id else None,
            mastery_gap=mastery_gap,
            confidence_gap=confidence_gap,
            quality_score=self._safe_float(quality.get("quality_score"), 0.6),
            concept_relevance=concept_gap_fit,
        )
        base = self._safe_float(gain_payload.get("expected_learning_gain"), 0.0)
        if mode == "reinforce_weaknesses":
            base += 0.08 * mastery_gap
        return self._clamp(base)

    def _fatigue_penalty(
        self,
        *,
        learner_state: Dict[str, Any],
        resource: Dict[str, Any],
        explanation_time: int,
        mode: str,
    ) -> float:
        frustration = self._safe_float(learner_state.get("frustration_score"), 0.0)
        avg_session = max(self._safe_float(learner_state.get("avg_session_duration"), 12.0), 1.0)
        time_ratio = explanation_time / avg_session
        base = 0.35 * frustration + 0.35 * self._clamp(time_ratio / 2.5) + 0.15 * self._clamp(self._safe_float(learner_state.get("unfinished_resources"), 0.0) / 8.0)
        if mode == "quick_review" and explanation_time > 18:
            base += 0.18
        if learner_state.get("recovery_need_flag") and str(resource.get("type") or "").lower() in {"pdf", "text"} and explanation_time > 20:
            base += 0.15
        return self._clamp(base)

    def _redundancy_penalty(
        self,
        *,
        resource: Dict[str, Any],
        resource_key: str,
        recently_seen: Sequence[str],
        selected_topics: Sequence[str],
        selected_sources: Sequence[str],
    ) -> float:
        topic = str(resource.get("topic") or "").lower()
        source = str(resource.get("source") or "").lower()
        penalty = 0.0
        if resource_key in set(recently_seen):
            penalty += 0.5
        if topic and topic in set(selected_topics):
            penalty += 0.28
        if source and source in set(selected_sources):
            penalty += 0.14
        return self._clamp(penalty)

    def _compute_final_score(
        self,
        *,
        components: Dict[str, float],
        weights: ResourceRecommendationWeights,
    ) -> float:
        score = (
            weights.semantic_match * components["semantic_match"]
            + weights.concept_gap_fit * components["concept_gap_fit"]
            + weights.difficulty_fit * components["difficulty_fit"]
            + weights.goal_fit * components["goal_fit"]
            + weights.collaborative_score * components["collaborative_score"]
            + weights.pedagogical_fit * components["pedagogical_fit"]
            + weights.format_fit * components["format_fit"]
            + weights.engagement_fit * components["engagement_fit"]
            + weights.quality_score * components["quality_score"]
            + weights.expected_learning_gain * components["expected_learning_gain"]
            - weights.fatigue_penalty * components["fatigue_penalty"]
            - weights.redundancy_penalty * components["redundancy_penalty"]
        )
        return self._clamp(score)

    def _select_candidate_concept_ids(
        self,
        *,
        mode: str,
        goal_concepts: List[Dict[str, Any]],
        completed_concepts: Sequence[int],
        mastery_map: Dict[int, float],
        confidence_map: Dict[int, float],
    ) -> List[int]:
        completed_set = set(int(item) for item in completed_concepts)
        if mode == "learn_new":
            ordered = [
                int(item["concept_id"])
                for item in goal_concepts
                if int(item["concept_id"]) not in completed_set
                and mastery_map.get(int(item["concept_id"]), 0.0) <= 0.25
            ]
        elif mode == "reinforce_weaknesses":
            ordered = [
                int(item["concept_id"])
                for item in sorted(
                    goal_concepts,
                    key=lambda item: (
                        mastery_map.get(int(item["concept_id"]), 0.0),
                        confidence_map.get(int(item["concept_id"]), 0.0),
                    ),
                )
            ]
        else:
            ordered = [
                int(item["concept_id"])
                for item in goal_concepts
                if int(item["concept_id"]) not in completed_set
            ]
        fallback = [int(item["concept_id"]) for item in goal_concepts]
        unique: List[int] = []
        for concept_id in ordered + fallback:
            if concept_id not in unique:
                unique.append(concept_id)
        return unique[:10]

    def recommend_resources(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
        mode: str = "continue_learning",
    ) -> Dict[str, Any]:
        learner_state = self.learner_state_service.build_state(user_id)
        progress_rows = self.repository.get_user_progress(user_id)
        mastery_map = {
            int(item.get("concept_id", 0)): self._safe_float(item.get("mastery"), 0.0)
            for item in progress_rows
        }
        confidence_map = {
            int(item.get("concept_id", 0)): self._safe_float(item.get("confidence"), 0.0)
            for item in progress_rows
        }

        goal_concepts = self.repository.find_goal_concepts(goal=goal, limit=60)
        completed = [
            int(item["concept_id"])
            for item in goal_concepts
            if mastery_map.get(int(item["concept_id"]), 0.0) >= 0.8
        ]
        if not goal_concepts:
            return {
                "recommended": [],
                "completed_concepts": 0,
                "total_concepts": 0,
                "progress_percentage": 0.0,
                "reranking": {"strategy": "none", "diversity_ratio": 0.0},
                "learner_state": learner_state,
            }

        candidate_concept_ids = self._select_candidate_concept_ids(
            mode=mode,
            goal_concepts=goal_concepts,
            completed_concepts=completed,
            mastery_map=mastery_map,
            confidence_map=confidence_map,
        )
        fallback_level = {
            "beginner": "intermediate",
            "intermediate": "advanced",
            "advanced": "advanced",
        }
        preferred_levels = [level, fallback_level.get(level, level)]
        resources = self.repository.find_resources_for_concepts(
            concept_ids=candidate_concept_ids,
            preferred_levels=preferred_levels,
            limit=max(limit * 5, 25),
        )
        if not resources:
            progress_percentage = (len(completed) / len(goal_concepts) * 100.0) if goal_concepts else 0.0
            return {
                "recommended": [],
                "completed_concepts": len(completed),
                "total_concepts": len(goal_concepts),
                "progress_percentage": round(progress_percentage, 2),
                "reranking": {"strategy": "none", "diversity_ratio": 0.0},
                "learner_state": learner_state,
            }

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
        recently_seen = self.repository.get_recently_seen_resources(user_id=user_id, limit=24)
        focus_concepts = [str(item).lower() for item in learner_state.get("current_focus_concepts", [])]
        weights = self._weights_for_mode(mode)

        selected_topics: List[str] = []
        selected_sources: List[str] = []
        scored_items: List[Dict[str, Any]] = []
        for resource in resources:
            resource_key = self.repository.get_resource_key(resource)
            metadata = resource.get("metadata") or {}
            concept_id = int(resource.get("concept_id") or metadata.get("concept_id") or 0)
            mastery = mastery_map.get(concept_id, 0.0)
            confidence = confidence_map.get(concept_id, 0.0)
            quality = self.resource_quality_service.get_resource_quality(resource)

            pedagogical_fit = self._pedagogical_fit(
                level,
                str(metadata.get("pedagogy_type") or resource.get("pedagogy_type") or ""),
                mode,
            )
            format_fit = self._format_fit(user_pref, resource, mode)
            concept_gap_fit = self._concept_gap_fit(
                mastery=mastery,
                confidence=confidence,
                focus_concepts=focus_concepts,
                resource=resource,
            )
            expected_learning_gain = self._expected_learning_gain(
                resource_key=resource_key,
                concept_id=concept_id or None,
                mastery=mastery,
                confidence=confidence,
                quality=quality,
                concept_gap_fit=concept_gap_fit,
                mode=mode,
            )
            preview_explanation = self.explanation_service.build_explanation(
                resource=resource,
                mode=mode,
                learner_state=learner_state,
                score_breakdown={},
                goal=goal,
                level=level,
                quality_score=self._safe_float(quality.get("quality_score"), 0.0),
                expected_learning_gain=expected_learning_gain,
            )
            fatigue_penalty = self._fatigue_penalty(
                learner_state=learner_state,
                resource=resource,
                explanation_time=int(preview_explanation.get("estimated_time") or 12),
                mode=mode,
            )
            redundancy_penalty = self._redundancy_penalty(
                resource=resource,
                resource_key=resource_key,
                recently_seen=recently_seen,
                selected_topics=selected_topics,
                selected_sources=selected_sources,
            )

            components = {
                "semantic_match": round(self._semantic_match(goal_vector, resource), 6),
                "concept_gap_fit": round(concept_gap_fit, 6),
                "difficulty_fit": round(
                    self._difficulty_fit(level, str(resource.get("level") or level)), 6
                ),
                "goal_fit": round(self._goal_fit(goal_tokens, resource), 6),
                "collaborative_score": round(
                    self._safe_float(collaborative_scores.get(resource_key), 0.0), 6
                ),
                "pedagogical_fit": round(pedagogical_fit, 6),
                "format_fit": round(format_fit, 6),
                "engagement_fit": round(self._engagement_fit(quality, mode), 6),
                "quality_score": round(self._safe_float(quality.get("quality_score"), 0.0), 6),
                "expected_learning_gain": round(expected_learning_gain, 6),
                "fatigue_penalty": round(fatigue_penalty, 6),
                "redundancy_penalty": round(redundancy_penalty, 6),
            }
            final_score = self._compute_final_score(components=components, weights=weights)

            selected_topics.append(str(resource.get("topic") or "").lower())
            selected_sources.append(str(resource.get("source") or "").lower())
            scored_items.append(
                {
                    "resource": resource,
                    "resource_key": resource_key,
                    "components": components,
                    "quality": quality,
                    "final_base_score": round(final_score, 6),
                    "popularity": float(popularity_map.get(resource_key, 0.0)),
                    "is_recently_seen": resource_key in set(recently_seen),
                    "source": resource.get("source"),
                    "type": resource.get("type"),
                    "topic": resource.get("topic"),
                    "level": resource.get("level"),
                    "embedding": resource.get("embedding"),
                    "pedagogy_type": metadata.get("pedagogy_type") or resource.get("pedagogy_type"),
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

        recommended: List[Dict[str, Any]] = []
        for rank, item in enumerate(reranking_result.get("items", []), start=1):
            resource = item["resource"]
            quality = item["quality"]
            components = dict(item["components"])
            final_score = self._safe_float(item.get("rerank_score"), item.get("final_base_score", 0.0))
            explanation = self.explanation_service.build_explanation(
                resource=resource,
                mode=mode,
                learner_state=learner_state,
                score_breakdown=components,
                goal=goal,
                level=level,
                quality_score=self._safe_float(quality.get("quality_score"), 0.0),
                expected_learning_gain=self._safe_float(components.get("expected_learning_gain"), 0.0),
            )

            resource_identifier = resource.get("resource_id")
            if resource_identifier is None:
                resource_identifier = abs(hash(str(resource.get("_id")))) % 10_000_000
            try:
                serialized_resource_id: str | int = int(resource_identifier)
            except Exception:
                serialized_resource_id = str(resource_identifier)

            payload = {
                "resource_id": serialized_resource_id,
                "title": str(resource.get("title") or ""),
                "source": str(resource.get("source") or "unknown"),
                "level": str(resource.get("level") or level),
                "topic": str(resource.get("topic") or ""),
                "url": (resource.get("metadata") or {}).get("url") or resource.get("url"),
                "reason": explanation["reason"],
                "reason_tags": explanation["reason_tags"],
                "relevance_score": round(self._clamp(final_score), 4),
                "score_breakdown": components,
                "rank_position": rank,
                "recommendation_mode": mode,
                "estimated_time": explanation["estimated_time"],
                "primary_concepts": explanation["primary_concepts"],
                "quality_score": round(self._safe_float(quality.get("quality_score"), 0.0), 4),
                "expected_learning_gain": round(
                    self._safe_float(components.get("expected_learning_gain"), 0.0), 4
                ),
            }
            recommended.append(payload)
            self.explanation_collection.update_one(
                {
                    "user_id": str(user_id),
                    "resource_key": str(resource_identifier),
                    "mode": mode,
                },
                {"$set": {**payload, "updated_at": __import__("datetime").datetime.utcnow()}},
                upsert=True,
            )

        progress_percentage = (len(completed) / len(goal_concepts) * 100.0) if goal_concepts else 0.0
        return {
            "recommended": recommended,
            "completed_concepts": len(completed),
            "total_concepts": len(goal_concepts),
            "progress_percentage": round(progress_percentage, 2),
            "reranking": reranking_result.get("metadata", {}),
            "learner_state": learner_state,
            "recommendation_mode": mode,
        }

    def recommendation_debug_snapshot(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
        mode: str = "continue_learning",
    ) -> Dict[str, Any]:
        result = self.recommend_resources(
            user_id=user_id,
            goal=goal,
            level=level,
            limit=limit,
            enable_reranking=enable_reranking,
            mode=mode,
        )
        return {
            "input": {
                "user_id": str(user_id),
                "goal": goal,
                "level": level,
                "limit": limit,
                "mode": mode,
                "enable_reranking": enable_reranking,
            },
            "learner_state": result.get("learner_state", {}),
            "reranking": result.get("reranking", {}),
            "recommended_debug": result.get("recommended", []),
        }


hybrid_recommendation_service = HybridRecommendationService()
