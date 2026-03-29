"""Mastery state update logic for adaptive learning loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from backend.app.services.progress_evaluation_service import AttemptEvaluation


_DIFFICULTY_WEIGHTS = {
    "beginner": 0.8,
    "intermediate": 1.0,
    "advanced": 1.1,
}


@dataclass(frozen=True)
class MasteryUpdateResult:
    previous_lesson_mastery: float
    new_lesson_mastery: float
    chunk_mastery: Dict[str, float]
    concept_mastery: Dict[str, float]
    success_rate: float
    total_attempts: int


class MasteryUpdateService:
    """Update lesson/chunk/concept mastery with recency-aware smoothing."""

    RECENT_WEIGHT = 0.7
    HISTORY_WEIGHT = 0.3

    def update_mastery(
        self,
        previous_mastery: float,
        accuracy: float,
        difficulty_weight: float,
        recency_weight: float = RECENT_WEIGHT,
    ) -> float:
        observed = float(accuracy) * float(difficulty_weight)
        new_mastery = (float(previous_mastery) * (1.0 - recency_weight)) + (
            observed * recency_weight
        )
        return round(min(max(new_mastery, 0.0), 1.0), 2)

    def update_concept_mastery(
        self,
        concept_id: str,
        is_correct: bool,
        previous_score: float,
    ) -> float:
        """Increase/decrease concept mastery from a single observed response."""
        concept_bonus = 0.07 if bool(is_correct) else -0.09
        next_score = float(previous_score) + concept_bonus
        return round(max(0.0, min(1.0, next_score)), 4)

    def apply(
        self,
        *,
        previous_state: Dict[str, Any] | None,
        evaluation: AttemptEvaluation,
        questions: List[Dict[str, Any]],
        recommended_difficulty: str,
        recent_attempts: List[Dict[str, Any]] | None = None,
    ) -> MasteryUpdateResult:
        state = dict(previous_state or {})
        previous_lesson_mastery = float(state.get("lesson_mastery", 0.0) or 0.0)
        prev_attempts = int(state.get("total_attempts", 0) or 0)
        prev_success_rate = float(state.get("success_rate", 0.0) or 0.0)
        recent_attempts = list(recent_attempts or [])

        history_avg = 0.0
        if recent_attempts:
            history_avg = sum(
                float(item.get("accuracy", 0.0) or 0.0)
                for item in recent_attempts
                if isinstance(item, dict)
            ) / max(1, len(recent_attempts))

        difficulty_weight = _DIFFICULTY_WEIGHTS.get(
            str(recommended_difficulty).lower(),
            1.0,
        )
        blended_accuracy = (
            evaluation.accuracy * self.RECENT_WEIGHT
            + history_avg * self.HISTORY_WEIGHT
        )
        adjusted_accuracy = self._apply_trend_adjustment(
            accuracy=blended_accuracy,
            trend=evaluation.trend,
        )
        adjusted_accuracy = self._adjust_accuracy_for_streaks(
            accuracy=evaluation.accuracy,
            questions=questions,
            fallback=adjusted_accuracy,
        )
        new_lesson_mastery = self.update_mastery(
            previous_mastery=previous_lesson_mastery,
            accuracy=adjusted_accuracy,
            difficulty_weight=difficulty_weight,
            recency_weight=self.RECENT_WEIGHT,
        )

        chunk_mastery = self._update_group_mastery(
            previous=state.get("chunk_mastery") or {},
            questions=questions,
        )
        concept_mastery = self._update_group_mastery(
            previous=state.get("concept_mastery") or {},
            questions=questions,
            key="concept_id",
            concept_mode=True,
        )

        total_attempts = prev_attempts + 1
        success_rate = (
            ((prev_success_rate * prev_attempts) + evaluation.accuracy) / total_attempts
            if total_attempts > 0
            else evaluation.accuracy
        )

        return MasteryUpdateResult(
            previous_lesson_mastery=round(previous_lesson_mastery, 4),
            new_lesson_mastery=round(new_lesson_mastery, 4),
            chunk_mastery=chunk_mastery,
            concept_mastery=concept_mastery,
            success_rate=round(max(0.0, min(1.0, success_rate)), 4),
            total_attempts=total_attempts,
        )

    def _update_group_mastery(
        self,
        *,
        previous: Dict[str, Any],
        questions: List[Dict[str, Any]],
        key: str = "chunk_id",
        concept_mode: bool = False,
    ) -> Dict[str, float]:
        mastery = {
            str(group_key): float(value)
            for group_key, value in dict(previous or {}).items()
            if str(group_key)
        }
        grouped: Dict[str, List[bool]] = {}
        for item in questions or []:
            group_key = str(item.get(key) or "").strip()
            if not group_key:
                continue
            grouped.setdefault(group_key, []).append(bool(item.get("is_correct")))

        for group_key, outcomes in grouped.items():
            local_accuracy = sum(1 for value in outcomes if value) / max(1, len(outcomes))
            prev_value = mastery.get(group_key, 0.0)
            if concept_mode:
                concept_score = prev_value
                for outcome in outcomes:
                    concept_score = self.update_concept_mastery(
                        concept_id=group_key,
                        is_correct=bool(outcome),
                        previous_score=concept_score,
                    )
                mastery[group_key] = concept_score
                continue
            streak_penalty = 0.15 if self._is_consecutive_failures(outcomes) else 0.0
            stability_boost = 0.08 if self._is_stable_success(outcomes) else 0.0
            observed = max(0.0, min(1.0, local_accuracy - streak_penalty + stability_boost))
            mastery[group_key] = round((prev_value * 0.35) + (observed * 0.65), 4)

        return mastery

    @staticmethod
    def _is_consecutive_failures(outcomes: List[bool]) -> bool:
        if len(outcomes) < 2:
            return False
        return outcomes[-1] is False and outcomes[-2] is False

    @staticmethod
    def _is_stable_success(outcomes: List[bool]) -> bool:
        if len(outcomes) < 2:
            return False
        return outcomes[-1] is True and outcomes[-2] is True

    def _adjust_accuracy_for_streaks(
        self,
        *,
        accuracy: float,
        questions: List[Dict[str, Any]],
        fallback: float | None = None,
    ) -> float:
        per_concept: Dict[str, List[bool]] = {}
        for item in questions or []:
            concept = str(item.get("concept_id") or "").strip()
            if not concept:
                continue
            per_concept.setdefault(concept, []).append(bool(item.get("is_correct")))

        penalty = 0.0
        boost = 0.0
        for outcomes in per_concept.values():
            if self._is_consecutive_failures(outcomes):
                penalty += 0.08
            elif self._is_stable_success(outcomes):
                boost += 0.04

        base = float(fallback) if fallback is not None else float(accuracy)
        adjusted = base - penalty + boost
        return max(0.0, min(1.0, adjusted))

    @staticmethod
    def _apply_trend_adjustment(*, accuracy: float, trend: str) -> float:
        adjusted = float(accuracy)
        if trend == "improving":
            adjusted += 0.05
        elif trend == "declining":
            adjusted -= 0.07
        return max(0.0, min(1.0, adjusted))


mastery_update_service = MasteryUpdateService()
