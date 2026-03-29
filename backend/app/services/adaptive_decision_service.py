"""Rule-based adaptive decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from backend.app.services.progress_evaluation_service import AttemptEvaluation


@dataclass(frozen=True)
class AdaptiveDecision:
    next_action: str
    recommended_difficulty: str
    recommended_bloom_levels: List[str]
    target_chunk_ids: List[str]
    target_concepts: List[str]
    allow_llm: bool
    prefer_template: bool
    retry_strategy: str
    weakest_concept: str
    fail_streak: int
    success_streak: int
    reason: str


class AdaptiveDecisionService:
    """Determine the next adaptive action based on performance and mastery."""

    def decide(
        self,
        *,
        evaluation: AttemptEvaluation,
        lesson_mastery: float,
        chunk_mastery: Dict[str, float],
        concept_mastery: Dict[str, float],
        retry_strategy: str = "same_question",
    ) -> AdaptiveDecision:
        weak_chunks = [chunk for chunk, _ in evaluation.wrong_by_chunk[:3]]
        weak_concepts = [concept for concept, _ in evaluation.wrong_by_concept[:3]]
        weakest_concept = self._resolve_weakest_concept(
            weak_concepts=weak_concepts,
            concept_mastery=concept_mastery,
        )

        if evaluation.fail_streak >= 3:
            return AdaptiveDecision(
                next_action="force_remedial_mode",
                recommended_difficulty="beginner",
                recommended_bloom_levels=["remember", "understand"],
                target_chunk_ids=weak_chunks,
                target_concepts=[weakest_concept] if weakest_concept else weak_concepts,
                allow_llm=False,
                prefer_template=True,
                retry_strategy=retry_strategy,
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="Fail streak >= 3; forcing remedial mode",
            )

        if evaluation.success_streak >= 3:
            return AdaptiveDecision(
                next_action="increase_difficulty_fast",
                recommended_difficulty="advanced",
                recommended_bloom_levels=["apply", "analyze"],
                target_chunk_ids=weak_chunks,
                target_concepts=weak_concepts,
                allow_llm=True,
                prefer_template=False,
                retry_strategy="same_question",
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="Success streak >= 3; increase difficulty faster",
            )

        if evaluation.accuracy < 0.5:
            return AdaptiveDecision(
                next_action="review_same_chunk",
                recommended_difficulty="beginner",
                recommended_bloom_levels=["remember", "understand"],
                target_chunk_ids=weak_chunks,
                target_concepts=[weakest_concept] if weakest_concept else weak_concepts,
                allow_llm=False,
                prefer_template=True,
                retry_strategy=retry_strategy,
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="Low accuracy; review weakest chunk(s)",
            )

        repeated_weak_concept = self._has_repeated_weak_concept(concept_mastery)
        if repeated_weak_concept:
            return AdaptiveDecision(
                next_action="practice_specific_concept",
                recommended_difficulty="beginner",
                recommended_bloom_levels=["remember", "understand"],
                target_chunk_ids=weak_chunks,
                target_concepts=[repeated_weak_concept],
                allow_llm=False,
                prefer_template=True,
                retry_strategy=retry_strategy,
                weakest_concept=repeated_weak_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason=f"Repeated low performance on concept {repeated_weak_concept}",
            )

        if evaluation.accuracy < 0.75:
            return AdaptiveDecision(
                next_action="practice_similar_concepts",
                recommended_difficulty="intermediate" if lesson_mastery >= 0.6 else "beginner",
                recommended_bloom_levels=["understand", "apply"],
                target_chunk_ids=weak_chunks,
                target_concepts=[weakest_concept] if weakest_concept else weak_concepts,
                allow_llm=False,
                prefer_template=True,
                retry_strategy=retry_strategy,
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="Medium accuracy; continue focused practice",
            )

        if evaluation.accuracy >= 0.85 and lesson_mastery >= 0.8:
            return AdaptiveDecision(
                next_action="increase_difficulty",
                recommended_difficulty="advanced",
                recommended_bloom_levels=["apply", "analyze"],
                target_chunk_ids=weak_chunks,
                target_concepts=weak_concepts,
                allow_llm=True,
                prefer_template=False,
                retry_strategy="same_question",
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="High accuracy and mastery; increase challenge",
            )

        if evaluation.accuracy >= 0.75 and lesson_mastery >= 0.7:
            return AdaptiveDecision(
                next_action="advance_to_next_lesson",
                recommended_difficulty="intermediate",
                recommended_bloom_levels=["understand", "apply"],
                target_chunk_ids=weak_chunks,
                target_concepts=weak_concepts,
                allow_llm=True,
                prefer_template=False,
                retry_strategy="same_question",
                weakest_concept=weakest_concept,
                fail_streak=evaluation.fail_streak,
                success_streak=evaluation.success_streak,
                reason="Reached lesson completion threshold",
            )

        return AdaptiveDecision(
            next_action="continue_current_lesson",
            recommended_difficulty="intermediate" if lesson_mastery >= 0.6 else "beginner",
            recommended_bloom_levels=["understand", "apply"],
            target_chunk_ids=weak_chunks,
            target_concepts=[weakest_concept] if weakest_concept else weak_concepts,
            allow_llm=False,
            prefer_template=True,
            retry_strategy=retry_strategy,
            weakest_concept=weakest_concept,
            fail_streak=evaluation.fail_streak,
            success_streak=evaluation.success_streak,
            reason="Continue current lesson with targeted practice",
        )

    @staticmethod
    def _has_repeated_weak_concept(concept_mastery: Dict[str, float]) -> str:
        weak = [
            concept_id
            for concept_id, score in (concept_mastery or {}).items()
            if float(score) < 0.45
        ]
        return weak[0] if weak else ""

    @staticmethod
    def _resolve_weakest_concept(
        *,
        weak_concepts: List[str],
        concept_mastery: Dict[str, float],
    ) -> str:
        if weak_concepts:
            return weak_concepts[0]
        if not concept_mastery:
            return ""
        return min(concept_mastery.items(), key=lambda pair: float(pair[1]))[0]


adaptive_decision_service = AdaptiveDecisionService()
