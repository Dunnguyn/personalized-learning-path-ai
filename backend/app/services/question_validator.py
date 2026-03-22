"""Validation and normalization for lesson-scoped question generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence


@dataclass(frozen=True)
class ValidatedLessonQuestion:
    question_type: str
    question: str
    correct_answer: str
    distractors: List[str]
    explanation: str
    difficulty: str
    bloom_level: str
    chunk_ids: List[str]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class QuestionValidationPayload:
    status: str
    message: str
    questions: List[ValidatedLessonQuestion]
    errors: List[str]


class LessonScopedQuestionValidator:
    """Validate question JSON against lesson-scoped constraints."""

    allowed_question_types = {"multiple_choice", "short_answer", "true_false"}
    allowed_difficulties = {"beginner", "intermediate", "advanced"}
    allowed_bloom_levels = {"remember", "understand", "apply", "analyze"}

    def parse_and_validate(
        self,
        *,
        raw_text: str,
        allowed_chunk_ids: Sequence[str],
        chunk_text_by_id: Dict[str, str],
        target_count: int,
    ) -> QuestionValidationPayload:
        parsed = self._parse_json(raw_text)
        if not isinstance(parsed, dict):
            return QuestionValidationPayload(
                status="invalid",
                message="LLM output is not a JSON object.",
                questions=[],
                errors=["invalid_json"],
            )

        status = str(parsed.get("status") or "invalid").strip().lower()
        message = str(parsed.get("message") or "").strip()
        if status == "insufficient_context":
            return QuestionValidationPayload(
                status="insufficient_context",
                message=message or "Chunks do not contain enough grounded information.",
                questions=[],
                errors=[],
            )

        raw_questions = parsed.get("questions")
        if status != "ok" or not isinstance(raw_questions, list):
            return QuestionValidationPayload(
                status="invalid",
                message=message or "Question payload is malformed.",
                questions=[],
                errors=["invalid_status_or_questions"],
            )

        valid_questions: List[ValidatedLessonQuestion] = []
        errors: List[str] = []
        allowed_chunk_set = set(allowed_chunk_ids)
        for index, item in enumerate(raw_questions[:target_count]):
            try:
                question = self._normalize_question(item, allowed_chunk_set)
                for chunk_id in question.chunk_ids:
                    source_excerpt = str(question.metadata.get("source_excerpt") or "").strip()
                    chunk_text = str(chunk_text_by_id.get(chunk_id) or "")
                    if source_excerpt and self._normalize_text(source_excerpt) not in self._normalize_text(chunk_text):
                        raise ValueError("source_excerpt_not_in_chunk")
                valid_questions.append(question)
            except ValueError as exc:
                errors.append(f"question_{index}:{exc}")

        if not valid_questions:
            return QuestionValidationPayload(
                status="invalid",
                message=message or "No valid questions produced.",
                questions=[],
                errors=errors or ["no_valid_questions"],
            )

        return QuestionValidationPayload(
            status="ok",
            message=message or f"Generated {len(valid_questions)} questions.",
            questions=valid_questions,
            errors=errors,
        )

    def _normalize_question(
        self,
        item: Dict[str, Any],
        allowed_chunk_ids: set[str],
    ) -> ValidatedLessonQuestion:
        question_type = str(item.get("question_type") or "").strip()
        question = str(item.get("question") or "").strip()
        correct_answer = str(item.get("correct_answer") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        difficulty = str(item.get("difficulty") or "").strip().lower()
        bloom_level = str(item.get("bloom_level") or "").strip().lower()
        chunk_ids = [str(value).strip() for value in item.get("chunk_ids") or [] if str(value).strip()]
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        distractors = [str(value).strip() for value in item.get("distractors") or [] if str(value).strip()]

        if not question:
            raise ValueError("question_empty")
        if not correct_answer:
            raise ValueError("correct_answer_empty")
        if not explanation:
            raise ValueError("explanation_empty")
        if question_type not in self.allowed_question_types:
            raise ValueError("invalid_question_type")
        if difficulty not in self.allowed_difficulties:
            raise ValueError("invalid_difficulty")
        if bloom_level not in self.allowed_bloom_levels:
            raise ValueError("invalid_bloom_level")
        if not chunk_ids:
            raise ValueError("missing_chunk_ids")
        if any(chunk_id not in allowed_chunk_ids for chunk_id in chunk_ids):
            raise ValueError("chunk_outside_lesson_scope")

        if question_type == "multiple_choice":
            if len(distractors) != 3:
                raise ValueError("invalid_distractor_count")
            normalized_options = {self._normalize_text(correct_answer), *(self._normalize_text(item) for item in distractors)}
            if len(normalized_options) != 4:
                raise ValueError("duplicate_answers")
        elif question_type == "short_answer":
            distractors = []
        elif question_type == "true_false":
            if correct_answer not in {"True", "False"}:
                raise ValueError("invalid_true_false_answer")
            distractors = ["False" if correct_answer == "True" else "True"]

        source_excerpt = str(metadata.get("source_excerpt") or "").strip()
        if not source_excerpt:
            raise ValueError("missing_source_excerpt")

        return ValidatedLessonQuestion(
            question_type=question_type,
            question=question,
            correct_answer=correct_answer,
            distractors=distractors,
            explanation=explanation,
            difficulty=difficulty,
            bloom_level=bloom_level,
            chunk_ids=chunk_ids,
            metadata=metadata,
        )

    @staticmethod
    def _parse_json(raw_text: str) -> Any:
        text = (raw_text or "").strip()
        if not text:
            return None
        candidates = [text]
        fenced = re.search(r"```json\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            candidates.append(fenced.group(1).strip())
        object_match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
        if object_match:
            candidates.append(object_match.group(1).strip())
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())
