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
    allowed_bloom_levels = {
        "remember",
        "understand",
        "apply",
        "analyze",
        "evaluate",
        "create",
    }
    question_type_aliases = {
        "multiple choice": "multiple_choice",
        "multiple-choice": "multiple_choice",
        "mcq": "multiple_choice",
        "quiz": "multiple_choice",
        "short answer": "short_answer",
        "short-answer": "short_answer",
        "open_answer": "short_answer",
        "open answer": "short_answer",
        "true false": "true_false",
        "true/false": "true_false",
        "true-false": "true_false",
        "boolean": "true_false",
    }
    difficulty_aliases = {
        "basic": "beginner",
        "easy": "beginner",
        "medium": "intermediate",
        "normal": "intermediate",
        "hard": "advanced",
    }
    bloom_level_aliases = {
        "knowledge": "remember",
        "comprehension": "understand",
        "application": "apply",
        "analysis": "analyze",
        "evaluation": "evaluate",
        "synthesis": "create",
    }
    true_false_aliases = {
        "true": "True",
        "false": "False",
        "đúng": "True",
        "dung": "True",
        "sai": "False",
        "yes": "True",
        "no": "False",
    }

    def parse_and_validate(
        self,
        *,
        raw_text: str,
        allowed_chunk_ids: Sequence[str],
        chunk_text_by_id: Dict[str, str],
        target_count: int,
        default_difficulty: str,
        default_bloom_levels: Sequence[str],
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
                question = self._normalize_question(
                    item, allowed_chunk_set, chunk_text_by_id
                )
                for chunk_id in question.chunk_ids:
                    source_excerpt = str(
                        question.metadata.get("source_excerpt") or ""
                    ).strip()
                    chunk_text = str(chunk_text_by_id.get(chunk_id) or "")
                    if source_excerpt and not self._excerpt_matches_chunk(
                        source_excerpt=source_excerpt, chunk_text=chunk_text
                    ):
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
        chunk_text_by_id: Dict[str, str],
        default_difficulty: str = "beginner",
        default_bloom_levels: Sequence[str] = ("understand",),
    ) -> ValidatedLessonQuestion:
        question_type = self._normalize_question_type(
            str(item.get("question_type") or "").strip()
        )
        question = str(item.get("question") or "").strip()
        correct_answer = str(item.get("correct_answer") or "").strip()
        question_type = self._infer_question_type(
            question_type=question_type, item=item, correct_answer=correct_answer
        )
        correct_answer = self._normalize_correct_answer(
            question_type=question_type, value=correct_answer
        )
        explanation = str(item.get("explanation") or "").strip()
        difficulty = (
            self._normalize_difficulty(
                str(item.get("difficulty") or "").strip().lower()
            )
            or default_difficulty
        )
        bloom_level = self._normalize_bloom_level(
            str(item.get("bloom_level") or "").strip().lower()
        ) or (list(default_bloom_levels)[0] if default_bloom_levels else "understand")
        chunk_ids = self._normalize_chunk_ids(item.get("chunk_ids"))
        metadata = (
            item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        )
        distractors = self._normalize_distractors(
            item=item, question_type=question_type, correct_answer=correct_answer
        )
        if not chunk_ids:
            chunk_ids = (
                self._normalize_chunk_ids(item.get("chunk_id"))
                or self._normalize_chunk_ids(metadata.get("chunk_ids"))
                or self._normalize_chunk_ids(metadata.get("chunk_id"))
            )

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
            if len(distractors) < 2:
                raise ValueError("invalid_distractor_count")
            normalized_options = {
                self._normalize_text(correct_answer),
                *(self._normalize_text(item) for item in distractors),
            }
            if len(normalized_options) != len(distractors) + 1:
                raise ValueError("duplicate_answers")
        elif question_type == "short_answer":
            distractors = []
        elif question_type == "true_false":
            if correct_answer not in {"True", "False"}:
                raise ValueError("invalid_true_false_answer")
            distractors = ["False" if correct_answer == "True" else "True"]

        source_excerpt = str(metadata.get("source_excerpt") or "").strip()
        if not source_excerpt and chunk_ids:
            source_excerpt = self._build_excerpt_from_chunk(
                chunk_text_by_id.get(chunk_ids[0]) or ""
            )
            if source_excerpt:
                metadata["source_excerpt"] = source_excerpt
        if not source_excerpt:
            raise ValueError("missing_source_excerpt")
        if not explanation:
            explanation = (
                f"Câu hỏi được suy ra từ đoạn trích: {source_excerpt[:180]}".strip()
            )

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
        text = (raw_text or "").replace("\ufeff", "").strip()
        if not text:
            return None
        # Remove non-printable control characters that occasionally leak from provider output.
        text = "".join(
            ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32
        )
        candidates = [text]
        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            candidates.append(fenced.group(1).strip())
        balanced_object = LessonScopedQuestionValidator._extract_balanced_json_object(
            text
        )
        if balanced_object:
            candidates.append(balanced_object)
        for candidate in candidates:
            parsed = LessonScopedQuestionValidator._safe_json_loads(candidate)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _safe_json_loads(candidate: str) -> Any:
        try:
            return json.loads(candidate)
        except Exception:
            repaired = LessonScopedQuestionValidator._repair_common_json_issues(
                candidate
            )
            if not repaired:
                return None
            try:
                return json.loads(repaired)
            except Exception:
                return None

    @staticmethod
    def _extract_balanced_json_object(text: str) -> str:
        start = text.find("{")
        if start < 0:
            return ""

        in_string = False
        escaped = False
        depth = 0
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()

        # If content is truncated, return the tail so repair logic can attempt closure.
        return text[start:].strip()

    @staticmethod
    def _repair_common_json_issues(candidate: str) -> str:
        text = (candidate or "").strip()
        if not text:
            return ""

        text = (
            text.replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )
        text = re.sub(r",\s*([}\]])", r"\1", text)
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

        return LessonScopedQuestionValidator._close_unterminated_json(text)

    @staticmethod
    def _close_unterminated_json(text: str) -> str:
        in_string = False
        escaped = False
        stack: List[str] = []
        out_chars: List[str] = []

        for ch in text:
            out_chars.append(ch)
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in {"}", "]"}:
                if stack and stack[-1] == ch:
                    stack.pop()
                elif stack:
                    return text

        if in_string:
            out_chars.append('"')
        while stack:
            out_chars.append(stack.pop())

        return "".join(out_chars).strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _normalize_question_type(self, value: str) -> str:
        normalized = self._normalize_text(value).replace("_", " ")
        return self.question_type_aliases.get(normalized, normalized.replace(" ", "_"))

    def _normalize_difficulty(self, value: str) -> str:
        normalized = self._normalize_text(value)
        return self.difficulty_aliases.get(normalized, normalized)

    def _normalize_bloom_level(self, value: str) -> str:
        normalized = self._normalize_text(value)
        return self.bloom_level_aliases.get(normalized, normalized)

    def _normalize_correct_answer(self, *, question_type: str, value: str) -> str:
        cleaned = value.strip()
        if question_type != "true_false":
            return cleaned
        normalized = self._normalize_text(cleaned)
        return self.true_false_aliases.get(normalized, cleaned)

    def _normalize_chunk_ids(self, raw_value: Any) -> List[str]:
        if isinstance(raw_value, list):
            return [str(value).strip() for value in raw_value if str(value).strip()]
        if isinstance(raw_value, str) and raw_value.strip():
            return [raw_value.strip()]
        return []

    def _normalize_distractors(
        self, *, item: Dict[str, Any], question_type: str, correct_answer: str
    ) -> List[str]:
        raw_distractors = item.get("distractors")
        distractors = (
            [
                str(value).strip()
                for value in raw_distractors or []
                if str(value).strip()
            ]
            if isinstance(raw_distractors, list)
            else []
        )
        if question_type != "multiple_choice":
            return distractors

        if len(distractors) >= 3:
            return distractors[:3]

        raw_choices = item.get("choices") or item.get("options")
        if isinstance(raw_choices, list):
            normalized_answer = self._normalize_text(correct_answer)
            derived = [
                str(value).strip()
                for value in raw_choices
                if str(value).strip()
                and self._normalize_text(str(value)) != normalized_answer
            ]
            for choice in derived:
                if self._normalize_text(choice) not in {
                    self._normalize_text(item) for item in distractors
                }:
                    distractors.append(choice)
                if len(distractors) >= 3:
                    break
        return distractors[:3]

    def _infer_question_type(
        self, *, question_type: str, item: Dict[str, Any], correct_answer: str
    ) -> str:
        if question_type in self.allowed_question_types:
            return question_type
        normalized_answer = self._normalize_text(correct_answer)
        if normalized_answer in self.true_false_aliases:
            return "true_false"
        if (
            isinstance(item.get("distractors"), list)
            or isinstance(item.get("choices"), list)
            or isinstance(item.get("options"), list)
        ):
            return "multiple_choice"
        return "short_answer"

    def _excerpt_matches_chunk(self, *, source_excerpt: str, chunk_text: str) -> bool:
        normalized_excerpt = self._normalize_text(source_excerpt)
        normalized_chunk = self._normalize_text(chunk_text)
        if not normalized_excerpt or not normalized_chunk:
            return False
        if (
            normalized_excerpt in normalized_chunk
            or normalized_chunk in normalized_excerpt
        ):
            return True

        excerpt_tokens = [
            token
            for token in re.findall(r"\b[a-z0-9_]+\b", normalized_excerpt)
            if len(token) >= 3
        ]
        chunk_tokens = set(
            token
            for token in re.findall(r"\b[a-z0-9_]+\b", normalized_chunk)
            if len(token) >= 3
        )
        if not excerpt_tokens or not chunk_tokens:
            return False

        overlap = sum(1 for token in excerpt_tokens if token in chunk_tokens)
        return overlap / max(len(excerpt_tokens), 1) >= 0.65

    def _build_excerpt_from_chunk(self, chunk_text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(chunk_text or "")).strip()
        if not normalized:
            return ""
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[\.\!\?])\s+", normalized)
            if item.strip()
        ]
        for sentence in sentences:
            if 60 <= len(sentence) <= 240:
                return sentence
        if len(normalized) <= 220:
            return normalized
        trimmed = normalized[:220].rsplit(" ", 1)[0].strip()
        return f"{trimmed}..."
