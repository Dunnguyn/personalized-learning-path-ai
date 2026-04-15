"""Rule-based adaptive decision engine."""

from __future__ import annotations

from dataclasses import dataclass
import re
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

    UNLOCK_NEXT_LESSON = "UNLOCK_NEXT_LESSON"
    ASSIGN_REMEDIAL_RESOURCE = "ASSIGN_REMEDIAL_RESOURCE"
    GENERATE_REINFORCEMENT_QUIZ = "GENERATE_REINFORCEMENT_QUIZ"
    RECOMMEND_SHORT_RESOURCE = "RECOMMEND_SHORT_RESOURCE"
    REVIEW_WEAK_CONCEPT = "REVIEW_WEAK_CONCEPT"
    NO_ACTION = "NO_ACTION"

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
    def _normalize_concept(value: Any) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    def _resolve_main_concept(
        self,
        *,
        snapshot: Dict[str, Any],
        lesson: Dict[str, Any] | None,
    ) -> str:
        if lesson:
            metadata = lesson.get("metadata") or {}
            for candidate in (
                metadata.get("main_concept"),
                metadata.get("concept"),
                lesson.get("concept_id"),
                next(iter(lesson.get("keywords") or []), None),
                next(iter(lesson.get("learning_objectives") or []), None),
                lesson.get("topic"),
                lesson.get("title"),
            ):
                concept = self._normalize_concept(candidate)
                if concept:
                    return concept
        for concept in snapshot.get("mastery_by_concept", {}):
            normalized = self._normalize_concept(concept)
            if normalized:
                return normalized
        return ""

    def decide_next_action(
        self,
        snapshot: Dict[str, Any],
        lesson: Dict[str, Any] | None,
        prerequisites_ok: bool = True,
    ) -> Dict[str, Any]:
        mastery_by_concept = {
            self._normalize_concept(key): self._clamp(value)
            for key, value in (snapshot.get("mastery_by_concept") or {}).items()
            if self._normalize_concept(key)
        }
        main_concept = self._resolve_main_concept(snapshot=snapshot, lesson=lesson)
        if main_concept and main_concept not in mastery_by_concept:
            mastery_by_concept[main_concept] = self._clamp(
                self._safe_float(snapshot.get("quiz_accuracy"), 0.0)
            )
        weakest_concept = (
            min(mastery_by_concept.items(), key=lambda item: item[1])[0]
            if mastery_by_concept
            else main_concept
        )
        main_mastery = self._safe_float(
            mastery_by_concept.get(main_concept, 0.0),
            default=self._safe_float(snapshot.get("quiz_accuracy"), 0.0),
        )
        quiz_accuracy = self._safe_float(snapshot.get("quiz_accuracy"), 0.0)
        engagement_score = self._safe_float(snapshot.get("engagement_score"), 0.0)
        fatigue_score = self._safe_float(snapshot.get("fatigue_score"), 0.0)
        fail_streak = int(snapshot.get("fail_streak") or 0)

        if main_mastery >= 0.75 and prerequisites_ok:
            return {
                "action": self.UNLOCK_NEXT_LESSON,
                "reason": "Main concept mastery reached the unlock threshold.",
                "target_concepts": [main_concept] if main_concept else [],
                "should_unlock_next": True,
                "should_generate_quiz": False,
                "resource_ids": [],
                "metadata": {
                    "main_concept_mastery": round(main_mastery, 4),
                    "prerequisites_ok": True,
                },
            }

        if quiz_accuracy < 0.5 and fail_streak >= 2:
            return {
                "action": self.ASSIGN_REMEDIAL_RESOURCE,
                "reason": "Quiz accuracy below threshold and fail streak is high.",
                "target_concepts": [weakest_concept] if weakest_concept else [],
                "should_unlock_next": False,
                "should_generate_quiz": False,
                "resource_ids": [],
                "metadata": {
                    "quiz_accuracy": round(quiz_accuracy, 4),
                    "fail_streak": fail_streak,
                },
            }

        if engagement_score < 0.4:
            return {
                "action": self.RECOMMEND_SHORT_RESOURCE,
                "reason": "Engagement is low, so a shorter resource is recommended.",
                "target_concepts": [weakest_concept] if weakest_concept else [],
                "should_unlock_next": False,
                "should_generate_quiz": False,
                "resource_ids": [],
                "metadata": {"engagement_score": round(engagement_score, 4)},
            }

        if fatigue_score > 0.8:
            return {
                "action": self.REVIEW_WEAK_CONCEPT,
                "reason": "Fatigue score is high; review the weakest concept before continuing.",
                "target_concepts": [weakest_concept] if weakest_concept else [],
                "should_unlock_next": False,
                "should_generate_quiz": False,
                "resource_ids": [],
                "metadata": {"fatigue_score": round(fatigue_score, 4)},
            }

        if main_mastery < 0.75:
            return {
                "action": self.GENERATE_REINFORCEMENT_QUIZ,
                "reason": "The lesson is not mastered yet, so a reinforcement quiz should come next.",
                "target_concepts": [weakest_concept] if weakest_concept else [],
                "should_unlock_next": False,
                "should_generate_quiz": True,
                "resource_ids": [],
                "metadata": {"main_concept_mastery": round(main_mastery, 4)},
            }

        return {
            "action": self.NO_ACTION,
            "reason": "No additional adaptive action is needed right now.",
            "target_concepts": [weakest_concept] if weakest_concept else [],
            "should_unlock_next": False,
            "should_generate_quiz": False,
            "resource_ids": [],
            "metadata": {
                "main_concept_mastery": round(main_mastery, 4),
                "prerequisites_ok": bool(prerequisites_ok),
            },
        }

    def decide(
        self,
        *,
        evaluation: AttemptEvaluation,
        lesson_mastery: float,
        chunk_mastery: Dict[str, float],
        concept_mastery: Dict[str, float],
        retry_strategy: str = "paraphrase_question",
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
                retry_strategy="paraphrase_question",
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
                retry_strategy="paraphrase_question",
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
                retry_strategy="paraphrase_question",
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
