"""LLM-backed lesson question generation service."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

from backend.app.ai_module import LessonQuestionLLMClient
from backend.app.services.prompt_builder import (
    LessonQuestionPromptContext,
    LessonScopedPromptBuilder,
)
from backend.app.services.question_validator import LessonScopedQuestionValidator
from backend.app.services.question_validator import (
    QuestionValidationPayload,
    ValidatedLessonQuestion,
)

logger = logging.getLogger(__name__)

LESSON_QA_PROMPT_MAX_CHUNKS = int(
    os.getenv("LESSON_QUESTION_LLM_PROMPT_MAX_CHUNKS", "8")
)
LESSON_QA_PROMPT_MAX_CHARS_PER_CHUNK = int(
    os.getenv("LESSON_QUESTION_LLM_PROMPT_MAX_CHARS_PER_CHUNK", "900")
)
LESSON_QA_VALIDATION_REPAIR_ATTEMPTS = int(
    os.getenv("LESSON_QUESTION_LLM_VALIDATION_REPAIR_ATTEMPTS", "2")
)


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
        chunk_payload = self._prepare_chunk_payload(
            chunk_payload=chunk_payload,
            target_count=target_count,
        )
        if target_count > 1:
            return self._generate_iteratively(
                context=context,
                chunk_payload=chunk_payload,
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
        return self._generate_once(
            context=context,
            chunk_payload=chunk_payload,
            allowed_chunk_ids=allowed_chunk_ids,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
        )

    def _generate_iteratively(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> QuestionValidationPayload:
        collected: List[ValidatedLessonQuestion] = []
        errors: List[str] = []
        seen_signatures: set[str] = set()

        for chunk in chunk_payload:
            if len(collected) >= target_count:
                break
            validation = self._generate_once(
                context=context,
                chunk_payload=[chunk],
                allowed_chunk_ids=[str(chunk.get("chunk_id") or "").strip()],
                target_count=1,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            if validation.status != "ok":
                errors.extend(list(validation.errors or []))
                debug_status = self.llm_client.get_debug_status()
                if bool(debug_status.get("cooldown_active")):
                    break
                last_error = str(self.llm_client.get_last_error() or "").lower()
                if "quota" in last_error or "resource_exhausted" in last_error:
                    break
                continue
            for question in validation.questions:
                signature = self._question_signature(question)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                collected.append(question)
                if len(collected) >= target_count:
                    break

        if collected:
            return QuestionValidationPayload(
                status="ok",
                message=f"Generated {len(collected)} questions.",
                questions=collected,
                errors=errors,
            )
        return QuestionValidationPayload(
            status="invalid",
            message="No valid questions produced.",
            questions=[],
            errors=errors or ["no_valid_questions"],
        )

    def _generate_once(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        allowed_chunk_ids: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> QuestionValidationPayload:
        chunk_text_by_id = {
            str(item.get("chunk_id")): str(item.get("content") or "")
            for item in chunk_payload
        }
        chunk_metadata_by_id = {
            str(item.get("chunk_id")): {
                "resource_id": str(item.get("resource_id") or "").strip(),
                "resource_title": str(item.get("resource_title") or "").strip(),
                "chunk_index": item.get("chunk_index"),
                "page_number": item.get("page_number"),
                "covered_concepts": list(item.get("covered_concepts") or []),
            }
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
        for attempt in range(max(1, LESSON_QA_VALIDATION_REPAIR_ATTEMPTS)):
            raw_text = self.llm_client.generate(retry_prompt or prompt)
            if not (raw_text or "").strip():
                llm_error = self.llm_client.get_last_error() or "empty_response"
                logger.warning(
                    "lesson_question_generation_llm_empty | lesson_id=%s | attempt=%s | llm_error=%s",
                    str(context["lesson"]["_id"]),
                    attempt + 1,
                    llm_error,
                )
                return QuestionValidationPayload(
                    status="invalid",
                    message=f"LLM empty response: {llm_error}",
                    questions=[],
                    errors=["empty_response"],
                )

            validation = self.validator.parse_and_validate(
                raw_text=raw_text,
                allowed_chunk_ids=allowed_chunk_ids,
                chunk_text_by_id=chunk_text_by_id,
                chunk_metadata_by_id=chunk_metadata_by_id,
                target_count=target_count,
                default_difficulty=difficulty,
                default_bloom_levels=bloom_levels,
            )
            if validation.status in {"ok", "insufficient_context"}:
                return validation

            retry_prompt = self._build_repair_prompt(
                context=context,
                chunk_payload=chunk_payload,
                raw_text=raw_text,
                validation_errors=list(validation.errors or []),
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )

        return validation

    def _prepare_chunk_payload(
        self,
        *,
        chunk_payload: List[Dict[str, Any]],
        target_count: int,
    ) -> List[Dict[str, Any]]:
        if not chunk_payload:
            return []
        max_chunks = max(
            3,
            min(
                LESSON_QA_PROMPT_MAX_CHUNKS,
                max(target_count * 3, target_count + 2),
            ),
        )
        ranked_chunks = sorted(
            chunk_payload,
            key=lambda item: (
                float(item.get("questionability_score") or 0.0),
                float(item.get("score") or 0.0),
                len(str(item.get("covered_concepts") or [])),
                len(str(item.get("content") or "")),
            ),
            reverse=True,
        )
        prepared: List[Dict[str, Any]] = []
        for chunk in ranked_chunks[:max_chunks]:
            content = re.sub(r"\s+", " ", str(chunk.get("content") or "")).strip()
            if len(content) > LESSON_QA_PROMPT_MAX_CHARS_PER_CHUNK:
                content = content[:LESSON_QA_PROMPT_MAX_CHARS_PER_CHUNK].rsplit(" ", 1)[
                    0
                ]
                content = f"{content}..."
            prepared.append(
                {
                    **chunk,
                    "content": content,
                }
            )
        return prepared

    def _build_repair_prompt(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        raw_text: str,
        validation_errors: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> str:
        compact_scope = [
            {
                "chunk_id": item.get("chunk_id"),
                "resource_id": item.get("resource_id"),
                "resource_title": item.get("resource_title"),
                "chunk_index": item.get("chunk_index"),
                "page_number": item.get("page_number"),
                "instruction_role": item.get("instruction_role"),
                "covered_concepts": item.get("covered_concepts"),
                "content_excerpt": str(item.get("content") or "")[:260],
            }
            for item in chunk_payload
        ]
        invalid_output = re.sub(r"\s+", " ", str(raw_text or "")).strip()[:5000]
        return f"""
Repair the invalid lesson-question JSON below.

Return valid JSON only with the same schema as before:
{{
  "status": "ok" | "insufficient_context",
  "message": "string",
  "questions": [
    {{
      "question_type": "multiple_choice" | "short_answer" | "true_false",
      "question": "string",
      "correct_answer": "string",
      "distractors": ["string", "string", "string"],
      "explanation": "string",
      "difficulty": "beginner" | "intermediate" | "advanced",
      "bloom_level": "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create",
      "chunk_ids": ["chunk_id"],
      "metadata": {{
        "source_excerpt": "string",
        "reasoning_note": "short string",
        "question_focus": "string",
        "source_page_number": 1,
        "source_resource_title": "string",
        "source_resource_id": "string",
        "source_chunk_index": 0,
        "source_score": 0.0
      }}
    }}
  ]
}}

Lesson:
{json.dumps({
    "lesson_title": str(context["lesson"].get("title") or ""),
    "lesson_summary": str(context["lesson"].get("summary") or ""),
    "target_count": target_count,
    "question_types": question_types,
    "difficulty": difficulty,
    "bloom_levels": bloom_levels,
}, ensure_ascii=False)}

Allowed chunk scope:
{json.dumps(compact_scope, ensure_ascii=False, indent=2)}

Previous output errors:
{json.dumps(validation_errors, ensure_ascii=False)}

Previous invalid output:
{invalid_output}

Repair rules:
- Every question must include exactly one valid `chunk_ids` item from the allowed scope.
- If `chunk_ids` is missing, infer it from `source_excerpt`, `question_focus`, `resource_id`, `resource_title`, `chunk_index`, or `page_number`.
- If `correct_answer` is missing, rewrite the question so the correct answer is explicit and grounded.
- Keep learner-facing text in Vietnamese.
- Use only the allowed chunk scope.
- For `multiple_choice`, provide exactly 3 distractors and ensure they differ from the correct answer.
- If you cannot repair faithfully, return `{{"status":"insufficient_context","message":"...","questions":[]}}`.
""".strip()

    @staticmethod
    def _question_signature(question: ValidatedLessonQuestion) -> str:
        question_key = re.sub(r"\s+", " ", question.question.strip().lower())
        answer_key = re.sub(r"\s+", " ", question.correct_answer.strip().lower())
        return f"{question.question_type}|{question_key[:160]}|{answer_key[:80]}"


question_llm_service: QuestionLLMService | None = None
