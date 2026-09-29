"""LLM-backed lesson question generation service."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from copy import deepcopy
from threading import Event, Lock
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
    os.getenv("LESSON_QUESTION_LLM_VALIDATION_REPAIR_ATTEMPTS", "1")
)
LESSON_QA_ITERATIVE_CHUNK_FILL_ENABLED = (
    os.getenv("LESSON_QUESTION_LLM_ITERATIVE_CHUNK_FILL_ENABLED", "false")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
LESSON_QA_REPAIR_SCOPE_EXCERPT_MAX_CHARS = int(
    os.getenv("LESSON_QUESTION_LLM_REPAIR_SCOPE_EXCERPT_MAX_CHARS", "160")
)
LESSON_QA_REPAIR_INVALID_OUTPUT_MAX_CHARS = int(
    os.getenv("LESSON_QUESTION_LLM_REPAIR_INVALID_OUTPUT_MAX_CHARS", "2200")
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
        self._inflight_lock = Lock()
        self._inflight_generations: Dict[str, Dict[str, Any]] = {}

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
            bloom_levels=bloom_levels,
        )
        generation_key = self._build_generation_key(
            context=context,
            chunk_payload=chunk_payload,
            allowed_chunk_ids=allowed_chunk_ids,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
        )
        generation_state, is_owner = self._acquire_generation_slot(generation_key)
        if not is_owner:
            lesson_id = str(context.get("lesson", {}).get("_id") or "").strip()
            logger.info(
                "lesson_question_generation_join_inflight | lesson_id=%s | key=%s",
                lesson_id,
                generation_key[:12],
            )
            generation_state["event"].wait()
            error = generation_state.get("error")
            if error is not None:
                raise error
            return deepcopy(generation_state["result"])

        try:
            batch_validation = self._generate_once(
                context=context,
                chunk_payload=chunk_payload,
                allowed_chunk_ids=allowed_chunk_ids,
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            if target_count <= 1:
                result = batch_validation
            elif (
                batch_validation.status == "ok"
                and len(batch_validation.questions) >= target_count
            ):
                result = batch_validation
            else:
                initial_questions = (
                    list(batch_validation.questions)
                    if batch_validation.status == "ok"
                    else []
                )
                used_chunk_ids = {
                    str(chunk_id).strip()
                    for question in initial_questions
                    for chunk_id in question.chunk_ids
                    if str(chunk_id).strip()
                }
                remaining_chunk_payload = [
                    chunk
                    for chunk in chunk_payload
                    if str(chunk.get("chunk_id") or "").strip() not in used_chunk_ids
                ]

                if (
                    target_count > len(initial_questions)
                    and remaining_chunk_payload
                    and LESSON_QA_ITERATIVE_CHUNK_FILL_ENABLED
                ):
                    result = self._generate_iteratively(
                        context=context,
                        chunk_payload=remaining_chunk_payload,
                        target_count=target_count,
                        question_types=question_types,
                        difficulty=difficulty,
                        bloom_levels=bloom_levels,
                        initial_questions=initial_questions,
                        initial_errors=list(batch_validation.errors or []),
                    )
                elif initial_questions:
                    result = QuestionValidationPayload(
                        status="ok",
                        message=f"Generated {len(initial_questions)} questions.",
                        questions=initial_questions,
                        errors=list(batch_validation.errors or []),
                    )
                else:
                    result = batch_validation

            generation_state["result"] = deepcopy(result)
            return result
        except Exception as exc:
            generation_state["error"] = exc
            raise
        finally:
            generation_state["event"].set()
            with self._inflight_lock:
                self._inflight_generations.pop(generation_key, None)

    def _generate_iteratively(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        initial_questions: List[ValidatedLessonQuestion] | None = None,
        initial_errors: List[str] | None = None,
    ) -> QuestionValidationPayload:
        collected: List[ValidatedLessonQuestion] = list(initial_questions or [])
        errors: List[str] = list(initial_errors or [])
        seen_signatures: set[str] = {
            self._question_signature(question) for question in collected
        }

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
        bloom_levels: List[str],
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
                self._chunk_generation_priority(
                    item,
                    bloom_levels=bloom_levels,
                ),
                float(item.get("questionability_score") or 0.0),
                float(item.get("score") or 0.0),
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

    def _chunk_generation_priority(
        self,
        chunk: Dict[str, Any],
        *,
        bloom_levels: List[str],
    ) -> float:
        content = re.sub(r"\s+", " ", str(chunk.get("content") or "")).strip()
        covered_concepts = [
            str(item).strip()
            for item in (chunk.get("covered_concepts") or [])
            if str(item).strip()
        ]
        instruction_role = str(chunk.get("instruction_role") or "").strip().lower()
        sentence_count = len(
            [part for part in re.split(r"[.!?]+", content) if str(part).strip()]
        )
        content_len = len(content)
        token_count = len(re.findall(r"\w+", content))
        code_like_hits = len(
            re.findall(r"[{}();=<>\[\]_]{1,}|`{1,3}|def\s+|class\s+|import\s+", content)
        )
        code_density = code_like_hits / max(token_count, 1)

        priority = float(chunk.get("questionability_score") or 0.0) * 1.7
        priority += float(chunk.get("score") or 0.0) * 1.25
        priority += min(len(covered_concepts), 4) * 0.22

        if 180 <= content_len <= 760:
            priority += 0.65
        elif 120 <= content_len <= 900:
            priority += 0.35
        else:
            priority -= 0.15

        if 2 <= sentence_count <= 6:
            priority += 0.45
        elif sentence_count == 1:
            priority -= 0.1
        elif sentence_count > 8:
            priority -= 0.08

        if code_density > 0.12:
            priority -= min(0.45, code_density * 1.2)

        requested_bloom = {
            str(level or "").strip().lower()
            for level in (bloom_levels or [])
            if str(level or "").strip()
        }
        if requested_bloom & {"apply", "analyze", "evaluate", "create"}:
            if instruction_role == "worked_example":
                priority += 0.7
            elif instruction_role in {"summary", "introduction"}:
                priority -= 0.12
        elif requested_bloom & {"understand", "remember"}:
            if instruction_role in {"introduction", "explanation"}:
                priority += 0.35

        return round(priority, 6)

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
        lesson_context = {
            "lesson_title": str(context["lesson"].get("title") or ""),
            "target_count": target_count,
            "question_types": question_types,
            "difficulty": difficulty,
            "bloom_levels": bloom_levels,
        }
        compact_scope = [
            {
                "chunk_id": item.get("chunk_id"),
                "chunk_index": item.get("chunk_index"),
                "page_number": item.get("page_number"),
                "instruction_role": item.get("instruction_role"),
                "covered_concepts": item.get("covered_concepts"),
                "content_excerpt": str(item.get("content") or "")[
                    :LESSON_QA_REPAIR_SCOPE_EXCERPT_MAX_CHARS
                ],
            }
            for item in chunk_payload
        ]
        invalid_output = re.sub(r"\s+", " ", str(raw_text or "")).strip()[
            :LESSON_QA_REPAIR_INVALID_OUTPUT_MAX_CHARS
        ]
        return f"""
Repair the invalid lesson-question JSON below.
Return valid JSON only:
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
        "question_focus": "string",
        "reasoning_pattern": "string",
        "distractor_rationale": ["string", "string", "string"],
        "evidence_terms": ["string"]
      }}
    }}
  ]
}}

Lesson:
{json.dumps(lesson_context, ensure_ascii=False, separators=(",", ":"))}

Allowed chunk scope:
{json.dumps(compact_scope, ensure_ascii=False, separators=(",", ":"))}

Validation errors:
{json.dumps(validation_errors[:8], ensure_ascii=False, separators=(",", ":"))}

Previous invalid output:
{invalid_output}

Repair rules:
- Each question must use exactly one allowed `chunk_id`.
- If `chunk_ids` is missing, infer it from `source_excerpt`, `question_focus`, `chunk_index`, or `page_number`.
- If `correct_answer` is missing, rewrite the question so the correct answer is explicit and grounded.
- Keep learner-facing text in Vietnamese.
- Use only the allowed chunk scope.
- For `multiple_choice`, provide exactly 3 distractors and ensure they differ from the correct answer.
- Do not ask a question whose answer is revealed directly in the question stem.
- Keep distractors plausible and in the same semantic family as the correct answer.
- Keep `distractor_rationale` empty for non-multiple_choice questions.
- Keep `explanation` tied to the `source_excerpt`, not generic background knowledge.
- If you cannot repair faithfully, return `{{"status":"insufficient_context","message":"...","questions":[]}}`.
""".strip()

    @staticmethod
    def _question_signature(question: ValidatedLessonQuestion) -> str:
        question_key = re.sub(r"\s+", " ", question.question.strip().lower())
        answer_key = re.sub(r"\s+", " ", question.correct_answer.strip().lower())
        return f"{question.question_type}|{question_key[:160]}|{answer_key[:80]}"

    def _acquire_generation_slot(self, generation_key: str) -> tuple[Dict[str, Any], bool]:
        with self._inflight_lock:
            current = self._inflight_generations.get(generation_key)
            if current is not None:
                return current, False
            created = {"event": Event(), "result": None, "error": None}
            self._inflight_generations[generation_key] = created
            return created, True

    def _build_generation_key(
        self,
        *,
        context: Dict[str, Any],
        chunk_payload: List[Dict[str, Any]],
        allowed_chunk_ids: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> str:
        lesson_id = str(context.get("lesson", {}).get("_id") or "").strip()
        payload = {
            "lesson_id": lesson_id,
            "target_count": int(target_count),
            "difficulty": str(difficulty or "").strip().lower(),
            "question_types": sorted(
                str(item).strip().lower() for item in question_types if str(item).strip()
            ),
            "bloom_levels": sorted(
                str(item).strip().lower() for item in bloom_levels if str(item).strip()
            ),
            "allowed_chunk_ids": sorted(
                str(item).strip() for item in allowed_chunk_ids if str(item).strip()
            ),
            "chunk_payload": [
                {
                    "chunk_id": str(item.get("chunk_id") or "").strip(),
                    "resource_id": str(item.get("resource_id") or "").strip(),
                    "chunk_index": item.get("chunk_index"),
                    "page_number": item.get("page_number"),
                    "covered_concepts": sorted(
                        str(concept).strip().lower()
                        for concept in (item.get("covered_concepts") or [])
                        if str(concept).strip()
                    ),
                    "content_sha1": hashlib.sha1(
                        str(item.get("content") or "").encode("utf-8")
                    ).hexdigest(),
                }
                for item in chunk_payload
            ],
        }
        raw_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()


question_llm_service: QuestionLLMService | None = None
