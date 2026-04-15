"""Validation helpers for hybrid lesson question generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from backend.app.services.question_validator import (
    LessonScopedQuestionValidator,
    ValidatedLessonQuestion,
)


@dataclass(frozen=True)
class ValidationResult:
    questions: List[ValidatedLessonQuestion]
    filtered_count: int


class QuestionValidationService:
    """Normalize, filter, and deduplicate generated question candidates."""

    def __init__(self, validator: LessonScopedQuestionValidator) -> None:
        self.validator = validator

    def validate_candidates(
        self,
        *,
        candidates: Sequence[Dict[str, Any]],
        allowed_chunk_ids: Sequence[str],
        chunk_text_by_id: Dict[str, str],
        default_difficulty: str,
        default_bloom_levels: Sequence[str],
    ) -> ValidationResult:
        valid: List[ValidatedLessonQuestion] = []
        filtered = 0
        allowed_chunk_set = set(allowed_chunk_ids)
        for item in candidates:
            try:
                normalized = self.validator._normalize_question(
                    dict(item),
                    allowed_chunk_set,
                    chunk_text_by_id,
                    {},
                    default_difficulty,
                    default_bloom_levels,
                )
            except Exception:
                filtered += 1
                continue
            valid.append(normalized)
        return ValidationResult(questions=valid, filtered_count=filtered)

    def merge_deduplicate(
        self,
        *,
        question_groups: Sequence[Sequence[ValidatedLessonQuestion]],
        target_count: int,
        max_per_chunk: int = 2,
    ) -> ValidationResult:
        merged: List[ValidatedLessonQuestion] = []
        signatures: set[str] = set()
        chunk_usage: Dict[str, int] = {}
        filtered = 0

        for group in question_groups:
            for item in group:
                signature = self._signature(item)
                if not signature:
                    filtered += 1
                    continue
                if signature in signatures:
                    filtered += 1
                    continue
                primary_chunk = next((chunk_id for chunk_id in item.chunk_ids if chunk_id), "")
                if primary_chunk and chunk_usage.get(primary_chunk, 0) >= max(1, max_per_chunk):
                    filtered += 1
                    continue
                signatures.add(signature)
                merged.append(item)
                if primary_chunk:
                    chunk_usage[primary_chunk] = chunk_usage.get(primary_chunk, 0) + 1
                if len(merged) >= target_count:
                    return ValidationResult(
                        questions=merged[:target_count],
                        filtered_count=filtered,
                    )

        return ValidationResult(questions=merged, filtered_count=filtered)

    @staticmethod
    def _signature(question: ValidatedLessonQuestion) -> str:
        question_text = " ".join(question.question.lower().split())
        answer_text = " ".join(question.correct_answer.lower().split())
        question_key = question_text[:160]
        answer_key = answer_text[:80]
        return f"{question.question_type}|{question_key}|{answer_key}"


question_validation_service: QuestionValidationService | None = None
