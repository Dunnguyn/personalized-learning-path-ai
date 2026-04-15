"""Lesson mastery scoring and academic completion evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence


_DIFFICULTY_WEIGHTS = {
    "beginner": 0.8,
    "intermediate": 1.0,
    "advanced": 1.2,
    "easy": 0.8,
    "medium": 1.0,
    "hard": 1.2,
}
_BLOOM_PASS_THRESHOLDS = {
    "remember": 0.70,
    "understand": 0.70,
    "apply": 0.60,
}
_CONFIDENCE_THRESHOLD = 0.60


@dataclass(frozen=True)
class LessonMasteryEvaluation:
    accuracy: float
    bloom_score: float
    bloom_accuracy_by_level: Dict[str, float]
    bloom_pass: bool
    concept_coverage_score: float
    concept_coverage_pass: bool
    difficulty_weighted_score: float
    confidence_score: float
    confidence_pass: bool
    mastery_score: float
    completion_status: str
    completed: bool
    reinforce_required: bool
    retry_required: bool
    critical_concept_failure: bool
    weak_concepts: List[str]
    critical_concepts: List[str]


class LessonMasteryService:
    """Evaluate lesson completion using academic mastery rules."""

    COMPLETION_THRESHOLD = 0.75
    REINFORCE_THRESHOLD = 0.50

    def evaluate_lesson_attempt(
        self,
        *,
        questions: Sequence[Dict[str, Any]],
        lesson_concepts: Sequence[str],
        critical_concepts: Sequence[str] | None = None,
        submitted_confidence: float | None = None,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
    ) -> LessonMasteryEvaluation:
        normalized_questions = [self._normalize_question(item) for item in questions or []]
        total_questions = len(normalized_questions)
        accuracy = (
            sum(1 for item in normalized_questions if item["is_correct"]) / total_questions
            if total_questions > 0
            else 0.0
        )

        bloom_accuracy_by_level = self._compute_bloom_accuracy(normalized_questions)
        bloom_score = self._compute_bloom_score(bloom_accuracy_by_level)
        bloom_pass = all(
            bloom_accuracy_by_level.get(level, 0.0) >= threshold
            for level, threshold in _BLOOM_PASS_THRESHOLDS.items()
        )

        lesson_concepts_normalized = self._normalize_concepts(lesson_concepts)
        critical_concepts_normalized = self._normalize_concepts(
            critical_concepts or lesson_concepts_normalized
        )
        concept_coverage_score, weak_concepts = self._compute_concept_coverage_score(
            normalized_questions,
            critical_concepts_normalized,
        )
        concept_coverage_pass = concept_coverage_score >= 0.70
        critical_concept_failure = self._has_critical_concept_failure(
            normalized_questions,
            critical_concepts_normalized,
        )

        difficulty_weighted_score = self._compute_difficulty_weighted_score(
            normalized_questions
        )
        confidence_score = self._resolve_confidence_score(
            normalized_questions=normalized_questions,
            submitted_confidence=submitted_confidence,
        )
        confidence_pass = confidence_score >= float(confidence_threshold)

        mastery_score = round(
            (0.35 * accuracy)
            + (0.25 * bloom_score)
            + (0.20 * concept_coverage_score)
            + (0.10 * difficulty_weighted_score)
            + (0.10 * confidence_score),
            4,
        )

        perfect_quiz_override = (
            total_questions > 0
            and accuracy >= 0.999
            and concept_coverage_pass
            and not critical_concept_failure
            and confidence_pass
            and mastery_score >= self.COMPLETION_THRESHOLD
        )
        completion_gate_pass = (
            accuracy >= 0.75
            and bloom_pass
            and concept_coverage_pass
            and not critical_concept_failure
            and confidence_pass
        )
        if (completion_gate_pass or perfect_quiz_override) and mastery_score >= self.COMPLETION_THRESHOLD:
            completion_status = "completed"
        elif mastery_score < self.REINFORCE_THRESHOLD:
            completion_status = "retry_required"
        else:
            completion_status = "reinforce_required"

        return LessonMasteryEvaluation(
            accuracy=round(accuracy, 4),
            bloom_score=round(bloom_score, 4),
            bloom_accuracy_by_level=bloom_accuracy_by_level,
            bloom_pass=bloom_pass,
            concept_coverage_score=round(concept_coverage_score, 4),
            concept_coverage_pass=concept_coverage_pass,
            difficulty_weighted_score=round(difficulty_weighted_score, 4),
            confidence_score=round(confidence_score, 4),
            confidence_pass=confidence_pass,
            mastery_score=mastery_score,
            completion_status=completion_status,
            completed=completion_status == "completed",
            reinforce_required=completion_status == "reinforce_required",
            retry_required=completion_status == "retry_required",
            critical_concept_failure=critical_concept_failure,
            weak_concepts=weak_concepts,
            critical_concepts=critical_concepts_normalized,
        )

    @staticmethod
    def difficulty_to_weight(label: str) -> float:
        return _DIFFICULTY_WEIGHTS.get(str(label or "").strip().lower(), 1.0)

    @staticmethod
    def lower_difficulty(label: str) -> str:
        normalized = str(label or "").strip().lower()
        if normalized in {"advanced", "hard"}:
            return "intermediate"
        if normalized in {"intermediate", "medium"}:
            return "beginner"
        return "beginner"

    @classmethod
    def _normalize_question(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        question = dict(item or {})
        metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
        confidence_score = question.get("confidence_score")
        if confidence_score is None:
            confidence_score = metadata.get("confidence_score")
        concepts = cls._normalize_concepts(
            [
                question.get("concept_id"),
                metadata.get("question_focus"),
                *(metadata.get("covered_concepts") or []),
                *(metadata.get("target_concepts") or []),
            ]
        )
        return {
            "is_correct": bool(question.get("is_correct")),
            "bloom_level": str(question.get("bloom_level") or "remember").strip().lower(),
            "difficulty": str(question.get("difficulty") or "beginner").strip().lower(),
            "confidence_score": max(0.0, min(1.0, float(confidence_score or 0.0))),
            "concepts": concepts,
        }

    @classmethod
    def _compute_bloom_accuracy(
        cls,
        questions: Sequence[Dict[str, Any]],
    ) -> Dict[str, float]:
        grouped: Dict[str, List[bool]] = {}
        for question in questions or []:
            level = str(question.get("bloom_level") or "remember").strip().lower()
            grouped.setdefault(level, []).append(bool(question.get("is_correct")))

        results: Dict[str, float] = {}
        for level in {"remember", "understand", "apply", "analyze"}:
            answers = grouped.get(level) or []
            if not answers:
                results[level] = 0.0
                continue
            results[level] = round(
                sum(1 for value in answers if value) / max(1, len(answers)),
                4,
            )
        return results

    @staticmethod
    def _compute_bloom_score(bloom_accuracy_by_level: Dict[str, float]) -> float:
        weighted = (
            (bloom_accuracy_by_level.get("remember", 0.0) * 0.25)
            + (bloom_accuracy_by_level.get("understand", 0.0) * 0.25)
            + (bloom_accuracy_by_level.get("apply", 0.0) * 0.30)
            + (bloom_accuracy_by_level.get("analyze", 0.0) * 0.20)
        )
        return max(0.0, min(1.0, weighted))

    @classmethod
    def _compute_concept_coverage_score(
        cls,
        questions: Sequence[Dict[str, Any]],
        critical_concepts: Sequence[str],
    ) -> tuple[float, List[str]]:
        critical = cls._normalize_concepts(critical_concepts)
        if not critical:
            return 1.0, []

        concept_stats: Dict[str, Dict[str, int]] = {
            concept: {"total": 0, "correct": 0}
            for concept in critical
        }
        for question in questions or []:
            question_concepts = cls._normalize_concepts(question.get("concepts") or [])
            if not question_concepts:
                continue
            for concept in critical:
                if concept not in set(question_concepts):
                    continue
                concept_stats[concept]["total"] += 1
                if bool(question.get("is_correct")):
                    concept_stats[concept]["correct"] += 1

        assessed_concepts = [
            concept for concept, stats in concept_stats.items() if stats["total"] > 0
        ]
        if not assessed_concepts:
            # Do not fail the learner when the generated quiz does not assess any
            # critical concept. Coverage quality should be enforced during generation.
            return 1.0, []

        mastered = []
        weak = []
        for concept in assessed_concepts:
            stats = concept_stats[concept]
            if (stats["correct"] / max(1, stats["total"])) >= 0.70:
                mastered.append(concept)
            else:
                weak.append(concept)
        return (len(mastered) / max(1, len(assessed_concepts))), weak

    @classmethod
    def _has_critical_concept_failure(
        cls,
        questions: Sequence[Dict[str, Any]],
        critical_concepts: Sequence[str],
    ) -> bool:
        critical = cls._normalize_concepts(critical_concepts)
        if not critical:
            return False

        for concept in critical:
            relevant = [
                question
                for question in questions or []
                if concept in set(cls._normalize_concepts(question.get("concepts") or []))
            ]
            if relevant and all(not bool(question.get("is_correct")) for question in relevant):
                return True
        return False

    @classmethod
    def _compute_difficulty_weighted_score(
        cls,
        questions: Sequence[Dict[str, Any]],
    ) -> float:
        if not questions:
            return 0.0
        total_weight = 0.0
        earned_weight = 0.0
        for question in questions or []:
            weight = cls.difficulty_to_weight(str(question.get("difficulty") or "beginner"))
            total_weight += weight
            if bool(question.get("is_correct")):
                earned_weight += weight
        if total_weight <= 0.0:
            return 0.0
        return max(0.0, min(1.0, earned_weight / total_weight))

    @staticmethod
    def _resolve_confidence_score(
        *,
        normalized_questions: Sequence[Dict[str, Any]],
        submitted_confidence: float | None,
    ) -> float:
        if submitted_confidence is not None:
            return max(0.0, min(1.0, float(submitted_confidence)))
        confidence_values = [
            float(item.get("confidence_score", 0.0) or 0.0)
            for item in normalized_questions or []
        ]
        if not confidence_values:
            return 0.0
        return max(0.0, min(1.0, sum(confidence_values) / len(confidence_values)))

    @staticmethod
    def _normalize_concepts(concepts: Iterable[Any]) -> List[str]:
        seen: set[str] = set()
        normalized: List[str] = []
        for concept in concepts or []:
            value = str(concept or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized


lesson_mastery_service = LessonMasteryService()
