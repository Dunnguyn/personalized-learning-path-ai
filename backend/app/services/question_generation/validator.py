from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from backend.app.services.question_generation.lesson_content import LessonChunk
from backend.app.services.question_generation.llm_generator import GeneratedLessonQuestion

logger = logging.getLogger(__name__)

GENERIC_PATTERNS = (
    "what is",
    "define ",
    "explain the lesson",
    "mo ta bai hoc",
)


@dataclass(frozen=True)
class LessonQuestionValidationResult:
    valid_questions: List[GeneratedLessonQuestion]
    rejected_count: int
    rejection_reasons: Dict[str, int]


class LessonQuestionValidator:
    """
    Heuristic validator for MVP question quality.

    Checks:
    - required fields
    - excerpt/chunk consistency
    - duplicate questions
    - excerpt exists inside retrieved chunk
    - avoid very generic prompts
    """

    def validate(
        self,
        questions: Sequence[GeneratedLessonQuestion],
        chunks: Sequence[LessonChunk],
        *,
        target_count: int,
    ) -> LessonQuestionValidationResult:
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        accepted: List[GeneratedLessonQuestion] = []
        seen_questions = set()
        rejection_reasons: Dict[str, int] = {}

        for question in questions:
            reason = self._validate_one(question=question, chunk_map=chunk_map, seen_questions=seen_questions)
            if reason is not None:
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                continue

            seen_questions.add(self._normalize(question.question))
            accepted.append(question)
            if len(accepted) >= target_count:
                break

        return LessonQuestionValidationResult(
            valid_questions=accepted,
            rejected_count=sum(rejection_reasons.values()),
            rejection_reasons=rejection_reasons,
        )

    def _validate_one(
        self,
        *,
        question: GeneratedLessonQuestion,
        chunk_map: Dict[str, LessonChunk],
        seen_questions: set[str],
    ) -> str | None:
        if not all(
            [
                question.question.strip(),
                question.answer.strip(),
                question.explanation.strip(),
                len(question.keywords) > 0,
                question.concept.strip(),
                question.source_excerpt.strip(),
                question.source_chunk_id.strip(),
            ]
        ):
            return "missing_field"

        if len(question.keywords) < 3 or len(question.keywords) > 5:
            return "invalid_keyword_count"

        if len(question.options) != 4:
            return "invalid_option_count"

        option_keys = [str(item.get("key", "")).strip().upper() for item in question.options]
        option_texts = [str(item.get("text", "")).strip() for item in question.options]
        if option_keys != ["A", "B", "C", "D"]:
            return "invalid_option_keys"
        if any(not text for text in option_texts):
            return "empty_option_text"
        if len({text.lower() for text in option_texts}) < 4:
            return "duplicate_option_text"
        if question.correct_option not in {"A", "B", "C", "D"}:
            return "invalid_correct_option"

        correct_text = ""
        for item in question.options:
            if str(item.get("key", "")).strip().upper() == question.correct_option:
                correct_text = str(item.get("text", "")).strip()
                break
        if not correct_text:
            return "correct_option_missing"
        if self._normalize(correct_text) != self._normalize(question.answer):
            return "answer_mismatch"

        if self._sentence_count(question.answer) > 2:
            return "answer_too_long"
        if self._sentence_count(question.explanation) > 3:
            return "explanation_too_long"
        if question.answer.strip() == "INSUFFICIENT_CONTEXT" and question.correct_option:
            return "insufficient_context_mcq"

        normalized_question = self._normalize(question.question)
        if normalized_question in seen_questions:
            return "duplicate_question"

        if len(question.source_excerpt.strip()) < 20:
            return "excerpt_too_short"

        if any(pattern in normalized_question for pattern in GENERIC_PATTERNS):
            if question.concept.lower() not in normalized_question:
                return "too_generic"

        source_chunk = chunk_map.get(question.source_chunk_id)
        if source_chunk is None:
            return "missing_chunk"

        normalized_excerpt = self._normalize(question.source_excerpt)
        normalized_chunk = self._normalize(source_chunk.text)
        if normalized_excerpt not in normalized_chunk:
            return "excerpt_not_in_chunk"

        if question.concept and question.concept.lower() not in normalized_question:
            # Allow if concept is clearly supported by excerpt.
            if question.concept.lower() not in normalized_excerpt:
                return "concept_not_grounded"

        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    @staticmethod
    def _sentence_count(text: str) -> int:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return 0
        parts = [item for item in re.split(r"[.!?]+", normalized) if item.strip()]
        return max(1, len(parts))


def validate_generated_lesson_questions(
    questions: Sequence[GeneratedLessonQuestion],
    chunks: Sequence[LessonChunk],
    *,
    target_count: int,
) -> LessonQuestionValidationResult:
    validator = LessonQuestionValidator()
    return validator.validate(questions=questions, chunks=chunks, target_count=target_count)
