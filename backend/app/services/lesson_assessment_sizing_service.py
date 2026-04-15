"""Lesson sizing and quiz planning helpers for adaptive lesson assessment."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Any, Dict, Iterable, List, Sequence


_LESSON_SIZE_ORDER = {
    "small": 0,
    "medium": 1,
    "large": 2,
}
_TARGET_QUESTION_COUNT = {
    "small": 6,
    "medium": 10,
    "large": 12,
}
_DIFFICULTY_RATIOS = (
    (0.4, {"easy": 0.60, "medium": 0.30, "hard": 0.10}),
    (0.7, {"easy": 0.30, "medium": 0.50, "hard": 0.20}),
    (1.1, {"easy": 0.20, "medium": 0.40, "hard": 0.40}),
)
_BLOOM_RATIOS = {
    "remember": 0.25,
    "understand": 0.25,
    "apply": 0.30,
    "analyze": 0.20,
}
_DIFFICULTY_LEVEL_MAP = {
    "easy": "beginner",
    "medium": "intermediate",
    "hard": "advanced",
}
_LEVEL_TO_DIFFICULTY_MAP = {
    "beginner": "easy",
    "intermediate": "medium",
    "advanced": "hard",
}


@dataclass(frozen=True)
class LessonAssessmentSizingResult:
    lesson_size: str
    chunk_count: int
    total_token_length: int
    concept_count: int
    estimated_learning_time: int
    target_count_auto: int
    difficulty_distribution: Dict[str, Any]
    bloom_distribution: Dict[str, Any]
    coverage_requirement: Dict[str, Any]
    concepts: List[str]


class LessonAssessmentSizingService:
    """Derive lesson sizing and quiz planning metadata."""

    def classify_lesson_size(
        self,
        *,
        chunk_count: int,
        total_token_length: int,
        concept_count: int,
        estimated_learning_time: int,
    ) -> str:
        chunk_count = max(0, int(chunk_count or 0))
        total_token_length = max(0, int(total_token_length or 0))
        concept_count = max(0, int(concept_count or 0))
        estimated_learning_time = max(0, int(estimated_learning_time or 0))

        size = "small"
        if chunk_count > 8 or concept_count > 6:
            size = "large"
        elif (4 <= chunk_count <= 8) or (4 <= concept_count <= 6):
            size = "medium"
        elif chunk_count <= 3 and concept_count <= 3:
            size = "small"

        token_time_size = "small"
        if total_token_length > 3200 or estimated_learning_time > 30:
            token_time_size = "large"
        elif total_token_length >= 1200 or estimated_learning_time >= 12:
            token_time_size = "medium"

        return max(size, token_time_size, key=lambda item: _LESSON_SIZE_ORDER[item])

    def calculate_target_question_count(self, lesson_size: str) -> int:
        return _TARGET_QUESTION_COUNT.get(str(lesson_size or "").strip().lower(), 6)

    def compute_difficulty_distribution(
        self,
        *,
        target_count: int,
        mastery: float | None,
    ) -> Dict[str, Any]:
        bounded_mastery = min(1.0, max(0.0, float(mastery or 0.0)))
        selected_ratios = _DIFFICULTY_RATIOS[-1][1]
        for threshold, ratio in _DIFFICULTY_RATIOS:
            if bounded_mastery < threshold:
                selected_ratios = ratio
                break

        counts = self._allocate_counts(target_count, selected_ratios)
        return {
            "mastery": round(bounded_mastery, 4),
            "ratios": dict(selected_ratios),
            "counts": counts,
            "level_counts": {
                _DIFFICULTY_LEVEL_MAP[key]: value for key, value in counts.items()
            },
        }

    def compute_bloom_distribution(
        self,
        *,
        target_count: int,
        lesson_size: str,
    ) -> Dict[str, Any]:
        counts = self._allocate_counts(target_count, _BLOOM_RATIOS)
        counts["apply"] = max(1, counts.get("apply", 0))
        if str(lesson_size).strip().lower() in {"medium", "large"}:
            counts["analyze"] = max(1, counts.get("analyze", 0))
        self._rebalance_counts(counts, target_count, preferred_order=["apply", "analyze"])
        return {
            "ratios": dict(_BLOOM_RATIOS),
            "counts": counts,
        }

    def validate_concept_coverage(
        self,
        *,
        questions: Sequence[Dict[str, Any]] | Sequence[Any],
        lesson_concepts: Sequence[str],
        minimum_rate: float = 0.8,
    ) -> Dict[str, Any]:
        normalized_lesson_concepts = self._normalize_concepts(lesson_concepts)
        if not normalized_lesson_concepts:
            return {
                "is_valid": True,
                "coverage_rate": 1.0,
                "required_concept_count": 0,
                "covered_concepts": [],
                "missing_concepts": [],
                "covered_count": 0,
                "total_concepts": 0,
            }

        required_concept_count = max(
            1,
            min(
                len(normalized_lesson_concepts),
                int(round(len(normalized_lesson_concepts) * float(minimum_rate) + 0.4999)),
            ),
        )
        covered = []
        for question in questions or []:
            covered.extend(self._extract_question_concepts(question))
        normalized_covered = self._normalize_concepts(covered)
        missing = [
            concept
            for concept in normalized_lesson_concepts
            if concept not in set(normalized_covered)
        ]
        covered_count = len(normalized_lesson_concepts) - len(missing)
        coverage_rate = covered_count / max(1, len(normalized_lesson_concepts))
        return {
            "is_valid": covered_count >= required_concept_count,
            "coverage_rate": round(min(1.0, max(0.0, coverage_rate)), 4),
            "required_concept_count": required_concept_count,
            "covered_concepts": normalized_covered,
            "missing_concepts": missing,
            "covered_count": covered_count,
            "total_concepts": len(normalized_lesson_concepts),
        }

    def build_quiz_plan(
        self,
        *,
        chunk_count: int,
        total_token_length: int,
        concept_count: int,
        estimated_learning_time: int,
        concepts: Sequence[str],
        mastery: float | None,
        requested_target_count: int | None,
    ) -> LessonAssessmentSizingResult:
        lesson_size = self.classify_lesson_size(
            chunk_count=chunk_count,
            total_token_length=total_token_length,
            concept_count=concept_count,
            estimated_learning_time=estimated_learning_time,
        )
        target_count_auto = self.calculate_target_question_count(lesson_size)
        resolved_target_count = max(
            1,
            int(requested_target_count)
            if requested_target_count is not None
            else target_count_auto,
        )
        difficulty_distribution = self.compute_difficulty_distribution(
            target_count=resolved_target_count,
            mastery=mastery,
        )
        bloom_distribution = self.compute_bloom_distribution(
            target_count=resolved_target_count,
            lesson_size=lesson_size,
        )
        coverage_requirement = self.validate_concept_coverage(
            questions=[],
            lesson_concepts=concepts,
        )
        return LessonAssessmentSizingResult(
            lesson_size=lesson_size,
            chunk_count=max(0, int(chunk_count or 0)),
            total_token_length=max(0, int(total_token_length or 0)),
            concept_count=max(0, int(concept_count or 0)),
            estimated_learning_time=max(0, int(estimated_learning_time or 0)),
            target_count_auto=target_count_auto,
            difficulty_distribution=difficulty_distribution,
            bloom_distribution=bloom_distribution,
            coverage_requirement=coverage_requirement,
            concepts=self._normalize_concepts(concepts),
        )

    @staticmethod
    def normalize_difficulty_label(value: str) -> str:
        label = str(value or "").strip().lower()
        return _LEVEL_TO_DIFFICULTY_MAP.get(label, label)

    @staticmethod
    def denormalize_difficulty_label(value: str) -> str:
        label = str(value or "").strip().lower()
        return _DIFFICULTY_LEVEL_MAP.get(label, label or "beginner")

    @classmethod
    def _allocate_counts(
        cls,
        target_count: int,
        ratios: Dict[str, float],
    ) -> Dict[str, int]:
        bounded_target = max(0, int(target_count or 0))
        raw = {
            key: float(bounded_target) * float(weight)
            for key, weight in dict(ratios or {}).items()
        }
        counts = {key: int(floor(value)) for key, value in raw.items()}
        remaining = bounded_target - sum(counts.values())
        remainders = sorted(
            ((raw[key] - counts[key], key) for key in raw),
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        index = 0
        while remaining > 0 and remainders:
            _, key = remainders[index % len(remainders)]
            counts[key] += 1
            remaining -= 1
            index += 1
        return counts

    @classmethod
    def _rebalance_counts(
        cls,
        counts: Dict[str, int],
        target_count: int,
        *,
        preferred_order: Sequence[str],
    ) -> None:
        bounded_target = max(0, int(target_count or 0))
        while sum(counts.values()) > bounded_target:
            candidate_key = next(
                (
                    key
                    for key in counts
                    if key not in set(preferred_order) and counts.get(key, 0) > 0
                ),
                None,
            )
            if candidate_key is None:
                candidate_key = next(
                    (key for key in counts if counts.get(key, 0) > 0),
                    None,
                )
            if candidate_key is None:
                break
            counts[candidate_key] -= 1

        while sum(counts.values()) < bounded_target:
            candidate_key = next(iter(preferred_order), None) or next(iter(counts), None)
            if candidate_key is None:
                break
            counts[candidate_key] = counts.get(candidate_key, 0) + 1

    @staticmethod
    def _normalize_concepts(concepts: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        normalized: List[str] = []
        for concept in concepts or []:
            value = str(concept or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @classmethod
    def _extract_question_concepts(cls, question: Any) -> List[str]:
        if hasattr(question, "metadata"):
            metadata = question.metadata if isinstance(question.metadata, dict) else {}
            concept_id = getattr(question, "concept_id", None)
        elif isinstance(question, dict):
            metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
            concept_id = question.get("concept_id")
        else:
            metadata = {}
            concept_id = None

        concepts: List[str] = []
        for key in (
            "covered_concepts",
            "target_concepts",
            "matched_required_concepts",
        ):
            value = metadata.get(key)
            if isinstance(value, list):
                concepts.extend(str(item) for item in value)
        if metadata.get("question_focus"):
            concepts.append(str(metadata.get("question_focus")))
        if concept_id:
            concepts.append(str(concept_id))
        return cls._normalize_concepts(concepts)


lesson_assessment_sizing_service = LessonAssessmentSizingService()
