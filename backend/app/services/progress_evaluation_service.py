"""Evaluate quiz attempt outcomes for adaptive loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class AttemptEvaluation:
    total_questions: int
    correct_count: int
    wrong_count: int
    accuracy: float
    average_confidence: float
    wrong_by_chunk: List[Tuple[str, int]]
    wrong_by_concept: List[Tuple[str, int]]
    wrong_by_difficulty: List[Tuple[str, int]]
    fail_streak: int = 0
    success_streak: int = 0
    trend: str = "stable"


class ProgressEvaluationService:
    """Compute attempt-level metrics and error aggregates."""

    def evaluate_attempt(
        self,
        questions: List[Dict[str, Any]],
        recent_attempts: List[Dict[str, Any]] | None = None,
    ) -> AttemptEvaluation:
        total = len(questions or [])
        correct = sum(1 for item in questions if bool(item.get("is_correct")))
        wrong = max(0, total - correct)
        accuracy = (correct / total) if total > 0 else 0.0

        confidence_values = [
            float(item.get("confidence_score", 0.0) or 0.0) for item in questions
        ]
        average_confidence = (
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        )

        history = list(recent_attempts or [])
        history_accuracies = [
            float(item.get("accuracy", 0.0) or 0.0)
            for item in history
            if isinstance(item, dict)
        ]
        history_accuracies.insert(0, accuracy)

        return AttemptEvaluation(
            total_questions=total,
            correct_count=correct,
            wrong_count=wrong,
            accuracy=round(accuracy, 4),
            average_confidence=round(max(0.0, min(1.0, average_confidence)), 4),
            wrong_by_chunk=self.aggregate_errors_by_chunk(questions),
            wrong_by_concept=self.aggregate_errors_by_concept(questions),
            wrong_by_difficulty=self.aggregate_errors_by_difficulty(questions),
            fail_streak=self.count_consecutive_failures(history_accuracies),
            success_streak=self.count_consecutive_success(history_accuracies),
            trend=self.compute_trend(history_accuracies),
        )

    @staticmethod
    def count_consecutive_failures(accuracies: List[float], threshold: float = 0.5) -> int:
        streak = 0
        for accuracy in accuracies:
            if float(accuracy) < threshold:
                streak += 1
                continue
            break
        return streak

    @staticmethod
    def count_consecutive_success(accuracies: List[float], threshold: float = 0.8) -> int:
        streak = 0
        for accuracy in accuracies:
            if float(accuracy) >= threshold:
                streak += 1
                continue
            break
        return streak

    @staticmethod
    def compute_trend(accuracies: List[float], epsilon: float = 0.03) -> str:
        if len(accuracies) < 2:
            return "stable"
        recent = float(accuracies[0])
        history = sum(float(value) for value in accuracies[1:]) / max(1, len(accuracies) - 1)
        delta = recent - history
        if delta > epsilon:
            return "improving"
        if delta < -epsilon:
            return "declining"
        return "stable"

    @staticmethod
    def aggregate_errors_by_chunk(questions: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
        bucket: Dict[str, int] = {}
        for item in questions or []:
            if bool(item.get("is_correct")):
                continue
            chunk_id = str(item.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            bucket[chunk_id] = bucket.get(chunk_id, 0) + 1
        return sorted(bucket.items(), key=lambda pair: pair[1], reverse=True)

    @staticmethod
    def aggregate_errors_by_concept(questions: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
        bucket: Dict[str, int] = {}
        for item in questions or []:
            if bool(item.get("is_correct")):
                continue
            concept_id = str(item.get("concept_id") or "").strip()
            if not concept_id:
                continue
            bucket[concept_id] = bucket.get(concept_id, 0) + 1
        return sorted(bucket.items(), key=lambda pair: pair[1], reverse=True)

    @staticmethod
    def aggregate_errors_by_difficulty(
        questions: List[Dict[str, Any]],
    ) -> List[Tuple[str, int]]:
        bucket: Dict[str, int] = {}
        for item in questions or []:
            if bool(item.get("is_correct")):
                continue
            level = str(item.get("difficulty") or "beginner").strip().lower()
            bucket[level] = bucket.get(level, 0) + 1
        return sorted(bucket.items(), key=lambda pair: pair[1], reverse=True)


progress_evaluation_service = ProgressEvaluationService()
