"""LLM-backed lesson question generation service."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.app.ai_module import LessonQuestionLLMClient
from backend.app.services.prompt_builder import (
    LessonQuestionPromptContext,
    LessonScopedPromptBuilder,
)
from backend.app.services.question_validator import LessonScopedQuestionValidator

logger = logging.getLogger(__name__)


class QuestionLLMService:
    """Generate lesson-scoped questions through the configured LLM provider."""

    def __init__(
        self,
        *,
        llm_client: LessonQuestionLLMClient,
        prompt_builder: LessonScopedPromptBuilder,
        validator: LessonScopedQuestionValidator,
    ) -> None:
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder
        self.validator = validator

    def generate(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        allowed_chunk_ids: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ):
        chunk_text_by_id = {
            str(item.get("chunk_id")): str(item.get("content") or "")
            for item in chunk_payload
        }
        prompt = self.prompt_builder.build(
            context=LessonQuestionPromptContext(
                subject_title=str(context["subject"].get("title") or ""),
                chapter_title=str(context["chapter"].get("title") or ""),
                lesson_id=str(context["lesson"]["_id"]),
                lesson_title=str(context["lesson"].get("title") or ""),
                lesson_summary=str(context["lesson"].get("summary") or ""),
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            ),
            chunks=chunk_payload,
        )

        validation = None
        retry_prompt = None
        for attempt in range(3):
            raw_text = self.llm_client.generate(retry_prompt or prompt)
            if not (raw_text or "").strip():
                llm_error = self.llm_client.get_last_error() or "empty_response"
                logger.warning(
                    "lesson_question_generation_llm_empty | lesson_id=%s | attempt=%s | llm_error=%s",
                    str(context["lesson"]["_id"]),
                    attempt + 1,
                    llm_error,
                )
                return type(
                    "FallbackValidationPayload",
                    (),
                    {
                        "status": "invalid",
                        "message": f"LLM empty response: {llm_error}",
                        "questions": [],
                        "errors": ["empty_response"],
                    },
                )()

            validation = self.validator.parse_and_validate(
                raw_text=raw_text,
                allowed_chunk_ids=allowed_chunk_ids,
                chunk_text_by_id=chunk_text_by_id,
                target_count=target_count,
                default_difficulty=difficulty,
                default_bloom_levels=bloom_levels,
            )
            if validation.status in {"ok", "insufficient_context"}:
                return validation

            repair_hint = (
                "Retry and return only valid JSON following the required schema. "
                "Normalize question_type to one of: multiple_choice, short_answer, true_false. "
                "If source_excerpt is missing, copy a short direct excerpt from the cited chunk. "
                "If difficulty or bloom_level is missing, fill them from the requested lesson context. "
                "For true_false, use correct_answer exactly True or False."
            )
            retry_prompt = (
                f"{prompt}\n\nPrevious output was invalid for these reasons: {validation.errors}. "
                f"{repair_hint}"
            )

        return validation


question_llm_service: QuestionLLMService | None = None