"""Lesson-scoped question generation and question bank storage."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List
import unicodedata

from backend.app.ai_module import LessonQuestionLLMClient
from backend.app.repositories import (
    LessonRecommendedChunkRepository,
    LessonRepository,
    QuestionBankRepository,
    ResourceChunkRepository,
    ResourceRepository,
)
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.prompt_builder import LessonScopedPromptBuilder
from backend.app.services.question_fallback_service import QuestionFallbackService
from backend.app.services.question_llm_service import QuestionLLMService
from backend.app.services.question_template_service import QuestionTemplateService
from backend.app.services.question_validation_service import QuestionValidationService
from backend.app.services.question_validator import (
    LessonScopedQuestionValidator,
    ValidatedLessonQuestion,
)

logger = logging.getLogger(__name__)

LOW_COUNT_REGEN_RETRY_ENABLED = (
    os.getenv("LESSON_QUESTION_LOW_COUNT_RETRY_ENABLED", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)
LOW_COUNT_REGEN_RETRY_DELAY_SECONDS = float(
    os.getenv("LESSON_QUESTION_LOW_COUNT_RETRY_DELAY_SECONDS", "1.5")
)
PREGEN_CHUNK_EXPANSION_ENABLED = (
    os.getenv("LESSON_QUESTION_PREGEN_CHUNK_EXPANSION_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
PREGEN_MIN_RECOMMENDED_CHUNKS = int(
    os.getenv("LESSON_QUESTION_PREGEN_MIN_RECOMMENDED_CHUNKS", "12")
)
QUESTION_GENERATION_REFRESH_MAX_CHUNKS = int(
    os.getenv("LESSON_QUESTION_REFRESH_MAX_CHUNKS", "16")
)
LOW_COUNT_FORCE_FILL_ENABLED = (
    os.getenv("LESSON_QUESTION_LOW_COUNT_FORCE_FILL_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
REINFORCEMENT_TRUE_FALSE_RATIO = float(
    os.getenv("LESSON_QUESTION_REINFORCEMENT_TRUE_FALSE_RATIO", "0.35")
)
REINFORCEMENT_STATEMENT_MAX_LEN = int(
    os.getenv("LESSON_QUESTION_REINFORCEMENT_STATEMENT_MAX_LEN", "170")
)
QUESTION_DIVERSITY_MAX_PER_CHUNK = int(
    os.getenv("LESSON_QUESTION_DIVERSITY_MAX_PER_CHUNK", "2")
)
QUESTION_CONFIDENCE_BASELINE = float(
    os.getenv("LESSON_QUESTION_CONFIDENCE_BASELINE", "0.2")
)


class LessonScopedQuestionGenerationService:
    """Generate questions only from already recommended lesson chunks."""

    _CONCEPT_ALIASES = {
        "bien": ["variable", "variables", "assignment", "value"],
        "kieu du lieu": [
            "data type",
            "type",
            "types",
            "string",
            "integer",
            "float",
            "boolean",
        ],
        "toan tu": [
            "operator",
            "operators",
            "expression",
            "arithmetic",
            "comparison",
            "logical",
        ],
        "list": ["list", "lists", "append", "sort", "index", "slice"],
        "dict": [
            "dict",
            "dictionary",
            "dictionaries",
            "key",
            "value",
            "keys",
            "values",
            "items",
        ],
        "dictionary": [
            "dict",
            "dictionary",
            "dictionaries",
            "key",
            "value",
            "keys",
            "values",
            "items",
        ],
        "tuple": ["tuple", "tuples", "pair", "pairs"],
        "set": ["set", "sets", "unique"],
        "ham": ["function", "functions", "method", "methods", "def", "return"],
        "vong lap": ["loop", "loops", "while", "for", "iteration", "iterable"],
        "dieu kien": ["condition", "conditional", "if", "elif", "else", "boolean"],
        "chuoi": ["string", "strings", "split", "strip", "text"],
        "tep": ["file", "files", "open", "read", "write"],
        "xu ly du lieu": [
            "data",
            "processing",
            "analysis",
            "count",
            "parse",
            "extract",
        ],
    }
    _STRICT_CONCEPT_ALIASES = {
        "bien": ["variable", "variables", "assignment"],
        "kieu du lieu": [
            "data type",
            "type",
            "types",
            "string",
            "integer",
            "float",
            "boolean",
        ],
        "toan tu": [
            "operator",
            "operators",
            "expression",
            "arithmetic",
            "comparison",
            "logical",
        ],
        "list": ["list", "lists", "append", "sort", "slice"],
        "dict": ["dict", "dictionary", "dictionaries", "key", "keys", "item", "items"],
        "dictionary": [
            "dict",
            "dictionary",
            "dictionaries",
            "key",
            "keys",
            "item",
            "items",
        ],
        "tuple": ["tuple", "tuples", "pair", "pairs"],
        "set": ["set", "sets", "unique"],
        "ham": ["function", "functions", "method", "methods", "def", "return"],
        "vong lap": ["loop", "loops", "while", "for", "iteration"],
        "dieu kien": ["condition", "conditional", "if", "elif", "else", "boolean"],
        "chuoi": ["string", "strings", "split", "strip", "text"],
        "tep": ["file", "files", "open", "read", "write"],
        "xu ly du lieu": ["data", "processing", "analysis"],
    }
    _FALLBACK_DISTRACTORS = [
        "tuple",
        "set",
        "loop",
        "function",
        "string",
        "module",
        "class",
        "boolean",
    ]
    _WEAK_DISTRACTOR_TERMS = {
        "module",
        "class",
        "value",
        "values",
        "item",
        "items",
        "type",
        "types",
        "data",
    }
    _FALLBACK_STOP_WORDS = {
        "about",
        "after",
        "also",
        "because",
        "before",
        "could",
        "each",
        "from",
        "have",
        "into",
        "just",
        "more",
        "most",
        "than",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "very",
        "what",
        "when",
        "where",
        "which",
        "would",
        "python",
        "program",
        "source",
        "book",
        "chapter",
        "debugging",
        "everybody",
        "fortunately",
        "frankly",
        "using",
        "used",
        "maintained",
        "github",
        "probably",
        "production",
        "fundamental",
        "includes",
        "include",
        "library",
        "libraries",
    }
    _IRRELEVANT_EXCERPT_PATTERNS = (
        r"\bcontributor list\b",
        r"\bcopyright\b",
        r"\bprinting history\b",
        r"\bpage \d+\b",
        r"\bindex\b",
        r"\bglossary\b",
    )
    _CATEGORY_POOLS = {
        "data_structure": [
            "ndarray",
            "array",
            "numpy",
            "list",
            "dict",
            "tuple",
            "set",
            "dictionary",
            "keys",
            "values",
            "items",
        ],
        "method": [
            "reshape",
            "astype",
            "sum",
            "mean",
            "index",
            "slice",
            "slicing",
            "iterator",
            "generator",
            "comprehension",
            "append",
            "sort",
            "items",
            "keys",
            "values",
            "split",
            "strip",
            "findall",
            "open",
            "read",
        ],
        "data_type": [
            "string",
            "integer",
            "float",
            "boolean",
            "value",
            "variable",
            "expression",
        ],
        "operator": [
            "operator",
            "arithmetic",
            "comparison",
            "logical",
            "expression",
            "assignment",
        ],
        "general": [
            "numpy",
            "ndarray",
            "array",
            "variable",
            "value",
            "expression",
            "function",
            "loop",
            "string",
            "module",
            "class",
        ],
    }
    _AMBIGUOUS_TERMS = {
        "data",
        "item",
        "items",
        "key",
        "keys",
        "type",
        "types",
        "value",
        "values",
    }
    _EXPLICIT_DOMAIN_TERMS = {
        "numpy",
        "ndarray",
        "array",
        "arrays",
        "matrix",
        "vector",
        "list",
        "dict",
        "dictionary",
        "tuple",
        "set",
        "shape",
        "dtype",
        "ndim",
        "size",
        "index",
        "slice",
        "slicing",
        "iterator",
        "iterators",
        "generator",
        "generators",
        "comprehension",
        "comprehensions",
        "function",
        "operator",
        "boolean",
        "integer",
        "float",
        "string",
        "method",
        "loop",
        "conditional",
    }

    def __init__(self) -> None:
        self.lesson_structure_service = lesson_structure_service
        self.lesson_chunk_service = lesson_chunk_service
        self.recommendation_repository = LessonRecommendedChunkRepository()
        self.lesson_repository = LessonRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.resource_repository = ResourceRepository()
        self.question_repository = QuestionBankRepository()
        self.prompt_builder = LessonScopedPromptBuilder()
        self.validator = LessonScopedQuestionValidator()
        self.llm_client = LessonQuestionLLMClient()
        self.question_template_service = QuestionTemplateService()
        self.question_fallback_service = QuestionFallbackService()
        self.question_validation_service = QuestionValidationService(self.validator)
        self.question_llm_service = QuestionLLMService(
            llm_client=self.llm_client,
            prompt_builder=self.prompt_builder,
            validator=self.validator,
        )

        self.recommendation_repository.ensure_indexes()
        self.resource_repository.ensure_indexes()
        self.question_repository.ensure_indexes()

    def generate_questions_for_lesson(
        self,
        *,
        lesson_id: str,
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        allow_llm: bool,
        mastery: float | None,
        success_rate: float | None,
        overwrite: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        source_stats = {
            "template": 0,
            "llm": 0,
            "local_fallback": 0,
            "existing_reuse": 0,
        }
        filtered_count = 0
        effective_difficulty = self._resolve_adaptive_difficulty(
            requested_difficulty=difficulty,
            mastery=mastery,
            success_rate=success_rate,
            metadata=metadata,
        )
        context = self.lesson_structure_service.get_lesson_context(lesson_id)
        recommendation = self._resolve_recommendation(lesson_id, context)
        existing_questions = self.question_repository.list_by_lesson(lesson_id)
        existing_count = len(existing_questions)

        recommendation, chunk_ids, chunks = self._load_generation_scope(
            lesson_id=lesson_id,
            context=context,
            recommendation=recommendation,
        )

        if (
            PREGEN_CHUNK_EXPANSION_ENABLED
            and len(chunk_ids) < PREGEN_MIN_RECOMMENDED_CHUNKS
        ):
            expanded = self._refresh_recommendation(
                lesson_id=lesson_id,
                metadata={
                    **metadata,
                    "trigger": "question_generation_pregen_expand",
                    "previous_chunk_count": len(chunk_ids),
                },
                max_chunks=QUESTION_GENERATION_REFRESH_MAX_CHUNKS,
            )
            if expanded:
                expanded_recommendation, expanded_chunk_ids, expanded_chunks = (
                    self._load_generation_scope(
                        lesson_id=lesson_id,
                        context=context,
                        recommendation=expanded,
                    )
                )
                if len(expanded_chunk_ids) > len(chunk_ids):
                    previous_chunk_count = len(chunk_ids)
                    recommendation = expanded_recommendation
                    chunk_ids = expanded_chunk_ids
                    chunks = expanded_chunks
                    logger.info(
                        "lesson_question_generation_pregen_expand | lesson_id=%s | chunks_before=%s | chunks_after=%s",
                        lesson_id,
                        previous_chunk_count,
                        len(chunk_ids),
                    )

        context = {
            **context,
            "recommendation_scores": recommendation.get("metadata", {}).get(
                "scores", {}
            ),
        }
        chunk_text_by_id = {
            str(chunk["_id"]): str(chunk.get("content") or "") for chunk in chunks
        }
        seeded_questions: List[ValidatedLessonQuestion] = []
        remaining_target = target_count
        if allow_llm:
            validation = self._run_generation(
                context=context,
                chunks=chunks,
                chunk_ids=chunk_ids,
                target_count=target_count,
                question_types=question_types,
                difficulty=effective_difficulty,
                bloom_levels=bloom_levels,
            )
        else:
            template_validation = self._build_template_validation(
                lesson_title=str(context["lesson"].get("title") or ""),
                chunks=chunks,
                target_count=target_count,
                question_types=question_types,
                difficulty=effective_difficulty,
                bloom_levels=bloom_levels,
                chunk_ids=chunk_ids,
                chunk_text_by_id=chunk_text_by_id,
            )
            seeded_questions = template_validation.questions[:target_count]
            source_stats["template"] = len(seeded_questions)
            filtered_count += template_validation.filtered_count

            remaining_target = max(0, target_count - len(seeded_questions))
            if remaining_target <= 0:
                validation = self._build_validation_from_fallback(
                    questions=[],
                    message="Template generator reached requested question count.",
                    status="ok",
                )
            else:
                local_candidates = self.question_fallback_service.build_candidates(
                    lesson_title=str(context["lesson"].get("title") or ""),
                    chunks=chunks,
                    target_count=remaining_target,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                )
                local_validation = self.question_validation_service.validate_candidates(
                    candidates=local_candidates,
                    allowed_chunk_ids=chunk_ids,
                    chunk_text_by_id=chunk_text_by_id,
                    default_difficulty=effective_difficulty,
                    default_bloom_levels=bloom_levels,
                )
                filtered_count += local_validation.filtered_count
                validation = self._build_validation_from_fallback(
                    questions=local_validation.questions,
                    message="LLM disabled; used deterministic local fallback only.",
                    status="ok"
                    if local_validation.questions
                    else "insufficient_context",
                )

        if validation.status == "insufficient_context":
            refreshed = self._refresh_recommendation(
                lesson_id=lesson_id,
                metadata=metadata,
            )
            if refreshed:
                recommendation, chunk_ids, chunks = self._load_generation_scope(
                    lesson_id=lesson_id,
                    context=context,
                    recommendation=refreshed,
                )
                context = {
                    **context,
                    "recommendation_scores": refreshed.get("metadata", {}).get(
                        "scores", {}
                    ),
                }
                if allow_llm:
                    validation = self._run_generation(
                        context=context,
                        chunks=chunks,
                        chunk_ids=chunk_ids,
                        target_count=remaining_target,
                        question_types=question_types,
                        difficulty=effective_difficulty,
                        bloom_levels=bloom_levels,
                    )
                else:
                    refreshed_chunk_text = {
                        str(chunk["_id"]): str(chunk.get("content") or "")
                        for chunk in chunks
                    }
                    local_candidates = self.question_fallback_service.build_candidates(
                        lesson_title=str(context["lesson"].get("title") or ""),
                        chunks=chunks,
                        target_count=remaining_target,
                        question_types=question_types,
                        difficulty=effective_difficulty,
                        bloom_levels=bloom_levels,
                        retry_attempts=3,
                    )
                    local_validation = self.question_validation_service.validate_candidates(
                        candidates=local_candidates,
                        allowed_chunk_ids=chunk_ids,
                        chunk_text_by_id=refreshed_chunk_text,
                        default_difficulty=effective_difficulty,
                        default_bloom_levels=bloom_levels,
                    )
                    filtered_count += local_validation.filtered_count
                    validation = self._build_validation_from_fallback(
                        questions=local_validation.questions,
                        message="LLM disabled; fallback retried with refreshed chunks.",
                        status="ok"
                        if local_validation.questions
                        else "insufficient_context",
                    )

        if validation is None:
            self._log_generation_outcome(
                lesson_id=lesson_id,
                status="insufficient_context",
                generation_mode="llm_error",
                question_count=0,
                chunk_count=len(chunk_ids),
                covered_chunk_count=0,
                llm_error=self.llm_client.get_last_error(),
                message="Question generation returned no valid validation payload.",
            )
            if allow_llm:
                validation = self._build_validation_from_fallback(
                    questions=[],
                    message=self._build_llm_fallback_message(
                        "KhÃ´ng thá»ƒ nháº­n pháº£n há»“i há»£p lá»‡ tá»« dá»‹ch vá»¥ táº¡o cÃ¢u há»i."
                    ),
                )
            else:
                return self._build_existing_or_insufficient_response(
                lesson_id=lesson_id,
                chunk_ids=chunk_ids,
                existing_count=existing_count,
                default_message="Không thể nhận phản hồi hợp lệ từ dịch vụ tạo câu hỏi.",
                source_stats=source_stats,
                filtered_count=filtered_count,
            )
        if validation.status == "insufficient_context":
            self._log_generation_outcome(
                lesson_id=lesson_id,
                status="insufficient_context",
                generation_mode="insufficient_context",
                question_count=0,
                chunk_count=len(chunk_ids),
                covered_chunk_count=0,
                llm_error=self.llm_client.get_last_error(),
                message=validation.message,
            )
            if allow_llm:
                validation = self._build_validation_from_fallback(
                    questions=[],
                    message=self._build_llm_fallback_message(validation.message),
                )
            else:
                return {
                    "lesson_id": lesson_id,
                    "status": "insufficient_context",
                    "generated_count": 0,
                    "saved_count": 0,
                    "question_ids": [],
                    "chunks_used": chunk_ids,
                    "insufficient_data": True,
                    "reused_existing": False,
                    "existing_count": existing_count,
                    "sources": source_stats,
                    "filtered_count": filtered_count,
                    "message": validation.message,
                }
        if validation.status != "ok":
            refreshed = self._refresh_recommendation(
                lesson_id=lesson_id,
                metadata={
                    **metadata,
                    "trigger": "fallback_quality_refresh",
                },
            )
            if refreshed:
                recommendation, chunk_ids, chunks = self._load_generation_scope(
                    lesson_id=lesson_id,
                    context=context,
                    recommendation=refreshed,
                )
                context = {
                    **context,
                    "recommendation_scores": refreshed.get("metadata", {}).get(
                        "scores", {}
                    ),
                }
            fallback_chunk_text = {
                str(chunk["_id"]): str(chunk.get("content") or "") for chunk in chunks
            }
            fallback_candidates = self.question_fallback_service.build_candidates(
                lesson_title=str(context["lesson"].get("title") or ""),
                chunks=chunks,
                target_count=target_count,
                question_types=question_types,
                difficulty=effective_difficulty,
                bloom_levels=bloom_levels,
                retry_attempts=3,
            )
            fallback_validation = self.question_validation_service.validate_candidates(
                candidates=fallback_candidates,
                allowed_chunk_ids=chunk_ids,
                chunk_text_by_id=fallback_chunk_text,
                default_difficulty=effective_difficulty,
                default_bloom_levels=bloom_levels,
            )
            filtered_count += fallback_validation.filtered_count
            fallback_questions = fallback_validation.questions
            if not fallback_questions:
                fallback_questions = self._build_fallback_questions(
                    context=context,
                    chunks=chunks,
                    target_count=target_count,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                )
            if not fallback_questions:
                return self._build_existing_or_insufficient_response(
                    lesson_id=lesson_id,
                    chunk_ids=chunk_ids,
                    existing_count=existing_count,
                    default_message="Hệ thống tạm thời chưa tạo được câu hỏi tự động từ nội dung bài học hiện tại.",
                    source_stats=source_stats,
                    filtered_count=filtered_count,
                )
            validation_message = validation.message or "LLM output invalid."
            validation = self._build_validation_from_fallback(
                questions=fallback_questions,
                message=self._build_llm_fallback_message(
                    f"Đã dùng chế độ tạo câu hỏi cục bộ vì dịch vụ AI chưa phản hồi đúng định dạng. {validation_message}"
                ),
            )

        chunk_text_by_id = {
            str(chunk["_id"]): str(chunk.get("content") or "") for chunk in chunks
        }
        if allow_llm:
            remaining_target = max(0, target_count - len(validation.questions))
            if remaining_target > 0:
                template_validation = self._build_template_validation(
                    lesson_title=str(context["lesson"].get("title") or ""),
                    chunks=chunks,
                    target_count=remaining_target,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                    chunk_ids=chunk_ids,
                    chunk_text_by_id=chunk_text_by_id,
                )
                seeded_questions = template_validation.questions[:remaining_target]
                source_stats["template"] = len(seeded_questions)
                filtered_count += template_validation.filtered_count

        merged_validation = self.question_validation_service.merge_deduplicate(
            question_groups=(
                [validation.questions, seeded_questions]
                if allow_llm
                else [seeded_questions, validation.questions]
            ),
            target_count=target_count,
            max_per_chunk=QUESTION_DIVERSITY_MAX_PER_CHUNK,
        )
        filtered_count += merged_validation.filtered_count
        llm_count = 0
        for item in merged_validation.questions:
            mode = str(item.metadata.get("generation_mode") or "").strip().lower()
            if mode == "template":
                continue
            if mode in {"local_fallback", "local_fill"}:
                source_stats["local_fallback"] += 1
                continue
            llm_count += 1
        source_stats["llm"] = llm_count

        finalized_questions, finalized_message = self._finalize_questions(
            context=context,
            chunks=chunks,
            questions=merged_validation.questions,
            target_count=target_count,
            question_types=question_types,
            difficulty=effective_difficulty,
            bloom_levels=bloom_levels,
            base_message=validation.message,
        )

        if 0 < len(finalized_questions) < target_count and existing_questions:
            existing_fill = self._build_existing_fill_questions(
                existing_questions=existing_questions,
                target_count=target_count - len(finalized_questions),
            )
            if existing_fill:
                known_signatures = {
                    self._question_signature(item)
                    for item in finalized_questions
                    if self._question_signature(item)
                }
                for candidate in existing_fill:
                    signature = self._question_signature(candidate)
                    if not signature or signature in known_signatures:
                        continue
                    known_signatures.add(signature)
                    finalized_questions.append(candidate)
                    source_stats["existing_reuse"] += 1
                    if len(finalized_questions) >= target_count:
                        break
                if len(finalized_questions) > 0:
                    finalized_message = (
                        f"{finalized_message} Hệ thống đã tái sử dụng câu hỏi đã kiểm chứng từ ngân hàng trước đó để bù số lượng còn thiếu."
                    )

        if (
            LOW_COUNT_REGEN_RETRY_ENABLED
            and 0 < len(finalized_questions) < target_count
            and validation.status == "ok"
        ):
            logger.info(
                "lesson_question_generation_low_count_retry | lesson_id=%s | generated=%s | target=%s | delay=%.2fs",
                lesson_id,
                len(finalized_questions),
                target_count,
                LOW_COUNT_REGEN_RETRY_DELAY_SECONDS,
            )
            time.sleep(max(0.0, LOW_COUNT_REGEN_RETRY_DELAY_SECONDS))
            retry_validation = self._run_generation(
                context=context,
                chunks=chunks,
                chunk_ids=chunk_ids,
                target_count=target_count,
                question_types=question_types,
                difficulty=effective_difficulty,
                bloom_levels=bloom_levels,
            )
            if retry_validation and retry_validation.status == "ok":
                retried_questions, retried_message = self._finalize_questions(
                    context=context,
                    chunks=chunks,
                    questions=retry_validation.questions,
                    target_count=target_count,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                    base_message=retry_validation.message,
                )
                if len(retried_questions) > len(finalized_questions):
                    finalized_questions = retried_questions
                    finalized_message = retried_message
                    logger.info(
                        "lesson_question_generation_low_count_retry_improved | lesson_id=%s | generated=%s | target=%s",
                        lesson_id,
                        len(finalized_questions),
                        target_count,
                    )

        if not finalized_questions:
            self._log_generation_outcome(
                lesson_id=lesson_id,
                status="insufficient_context",
                generation_mode="quality_filter_empty",
                question_count=0,
                chunk_count=len(chunk_ids),
                covered_chunk_count=0,
                llm_error=self.llm_client.get_last_error(),
                message="Quality filtering removed all generated questions.",
            )
            return self._build_existing_or_insufficient_response(
                lesson_id=lesson_id,
                chunk_ids=chunk_ids,
                existing_count=existing_count,
                default_message="Không đủ dữ liệu phù hợp để tạo bộ câu hỏi chất lượng cho bài học này.",
                source_stats=source_stats,
                filtered_count=filtered_count,
            )

        # Always replace existing question bank when a new valid set is generated.
        # This keeps one authoritative lesson-scoped set and avoids duplicate buildup.
        if overwrite or existing_count > 0:
            self.question_repository.delete_by_lesson(lesson_id)

        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        resource_ids = [str(item) for item in recommendation.get("resource_ids", [])]
        documents = []
        for question in finalized_questions:
            question_resource_ids = sorted(
                {
                    str(chunk_map[chunk_id]["resource_id"])
                    for chunk_id in question.chunk_ids
                    if chunk_id in chunk_map
                }
            )
            question_page_numbers = sorted(
                {
                    page_number
                    for chunk_id in question.chunk_ids
                    if chunk_id in chunk_map
                    for page_number in [
                        self.lesson_chunk_service._resolve_page_number(
                            chunk_map[chunk_id]
                        )
                    ]
                    if isinstance(page_number, int)
                }
            )
            question_chunk_indexes = sorted(
                {
                    int(chunk_map[chunk_id].get("chunk_index", 0))
                    for chunk_id in question.chunk_ids
                    if chunk_id in chunk_map
                }
            )
            resolved_concept = str(
                question.metadata.get("concept_id")
                or question.metadata.get("question_focus")
                or (metadata.get("target_concepts", [""])[0] if isinstance(metadata.get("target_concepts"), list) and metadata.get("target_concepts") else "")
                or "general"
            ).strip().lower()
            retry_strategy = str(
                metadata.get("retry_strategy")
                or metadata.get("generation_strategy", {}).get("retry_strategy")
                or "same_question"
            ).strip()
            documents.append(
                {
                    "subject_id": context["subject"]["_id"],
                    "chapter_id": context["chapter"]["_id"],
                    "lesson_id": context["lesson"]["_id"],
                    "chunk_ids": [
                        chunk_map[chunk_id]["_id"]
                        for chunk_id in question.chunk_ids
                        if chunk_id in chunk_map
                    ],
                    "resource_ids": [
                        chunk_map[chunk_id]["resource_id"]
                        for chunk_id in question.chunk_ids
                        if chunk_id in chunk_map
                    ],
                    "question_type": question.question_type,
                    "question": question.question,
                    "correct_answer": question.correct_answer,
                    "distractors": question.distractors,
                    "explanation": question.explanation,
                    "difficulty": question.difficulty,
                    "bloom_level": question.bloom_level,
                    "concept_id": resolved_concept,
                    "retry_strategy": retry_strategy,
                    "is_ai_generated": question.metadata.get("generation_mode")
                    != "local_fallback",
                    "llm_provider": (
                        self.llm_client.provider
                        if question.metadata.get("generation_mode") != "local_fallback"
                        else "local_fallback"
                    ),
                    "llm_model": (
                        self.llm_client.model
                        if question.metadata.get("generation_mode") != "local_fallback"
                        else None
                    ),
                    "metadata": {
                        **metadata,
                        **question.metadata,
                        "generation_source": str(
                            question.metadata.get("generation_source")
                            or question.metadata.get("generation_mode")
                            or "llm"
                        ),
                        "tracked_bloom_level": question.bloom_level,
                        "tracked_difficulty": question.difficulty,
                        "tracked_confidence_score": float(
                            question.metadata.get("confidence_score")
                            or question.metadata.get("quality_score")
                            or 0.0
                        ),
                        "lesson_recommendation_id": str(recommendation["_id"]),
                        "allowed_resource_ids": resource_ids,
                        "resolved_resource_ids": question_resource_ids,
                        "resolved_page_numbers": question_page_numbers,
                        "resolved_chunk_indexes": question_chunk_indexes,
                        "coverage_chunk_count": len(question.chunk_ids),
                    },
                }
            )

        inserted_ids = self.question_repository.insert_many(documents)
        generation_mode = self._determine_generation_mode(finalized_questions)
        covered_chunk_count = len(
            {
                chunk_id
                for question in finalized_questions
                for chunk_id in question.chunk_ids
            }
        )
        self._log_generation_outcome(
            lesson_id=lesson_id,
            status="ok",
            generation_mode=generation_mode,
            question_count=len(inserted_ids),
            chunk_count=len(chunk_ids),
            covered_chunk_count=covered_chunk_count,
            llm_error=self.llm_client.get_last_error(),
            message=finalized_message,
        )
        return {
            "lesson_id": lesson_id,
            "status": "ok",
            "generated_count": len(inserted_ids),
            "saved_count": len(inserted_ids),
            "question_ids": inserted_ids,
            "chunks_used": chunk_ids,
            "insufficient_data": False,
            "reused_existing": False,
            "existing_count": existing_count,
            "sources": source_stats,
            "filtered_count": filtered_count,
            "message": finalized_message,
        }

    def get_questions_for_lesson(self, lesson_id: str) -> Dict[str, Any]:
        questions = self.question_repository.list_by_lesson(lesson_id)
        serialized = []
        for question in questions:
            serialized.append(
                {
                    "question_id": str(question["_id"]),
                    "subject_id": str(question["subject_id"]),
                    "chapter_id": str(question["chapter_id"]),
                    "lesson_id": str(question["lesson_id"]),
                    "chunk_ids": [str(item) for item in question.get("chunk_ids", [])],
                    "resource_ids": [
                        str(item) for item in question.get("resource_ids", [])
                    ],
                    "question_type": question.get("question_type"),
                    "question": question.get("question"),
                    "correct_answer": question.get("correct_answer"),
                    "distractors": question.get("distractors", []),
                    "explanation": question.get("explanation"),
                    "difficulty": question.get("difficulty"),
                    "bloom_level": question.get("bloom_level"),
                    "concept_id": question.get("concept_id"),
                    "retry_strategy": question.get("retry_strategy"),
                    "is_ai_generated": bool(question.get("is_ai_generated", True)),
                    "llm_provider": question.get("llm_provider"),
                    "llm_model": question.get("llm_model"),
                    "generation_source": (
                        question.get("metadata", {}).get("generation_source")
                        if isinstance(question.get("metadata"), dict)
                        else None
                    ),
                    "confidence_score": (
                        question.get("metadata", {}).get("confidence_score")
                        if isinstance(question.get("metadata"), dict)
                        else None
                    ),
                    "metadata": question.get("metadata", {}),
                    "created_at": question.get("created_at"),
                }
            )
        return {
            "lesson_id": lesson_id,
            "total": len(serialized),
            "questions": serialized,
        }

    def _finalize_questions(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        questions: List[ValidatedLessonQuestion],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        base_message: str,
    ) -> tuple[List[ValidatedLessonQuestion], str]:
        chunk_order = [str(chunk["_id"]) for chunk in chunks]
        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        resource_ids = [
            str(chunk.get("resource_id"))
            for chunk in chunks
            if chunk.get("resource_id")
        ]
        resources = (
            self.resource_repository.get_many(resource_ids) if resource_ids else []
        )
        resource_map = {
            str(resource["_id"]): resource
            for resource in resources
            if resource.get("_id")
        }
        score_map = (
            context.get("recommendation_scores", {})
            if isinstance(context.get("recommendation_scores"), dict)
            else {}
        )

        ordered_questions = self._round_robin_questions_by_chunk_order(
            questions=questions,
            preferred_chunk_order=chunk_order,
            chunk_map=chunk_map,
            score_map=score_map,
        )
        fallback_questions: List[ValidatedLessonQuestion] = []

        finalized: List[ValidatedLessonQuestion] = []
        seen_signatures: set[str] = set()
        for candidate in ordered_questions:
            signature = self._question_signature(candidate)
            if not signature or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            finalized.append(
                self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
            )
            if len(finalized) >= target_count:
                break

        if len(finalized) < target_count:
            fallback_questions = self._build_fallback_questions(
                context=context,
                chunks=chunks,
                target_count=max(target_count + 4, target_count * 2),
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            for candidate in fallback_questions:
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                finalized.append(
                    self._enrich_question_metadata(
                        question=candidate,
                        chunk_map=chunk_map,
                        resource_map=resource_map,
                        score_map=score_map,
                        quality_score=self._score_question_quality(
                            candidate, chunk_map=chunk_map, score_map=score_map
                        ),
                    )
                )
                if len(finalized) >= target_count:
                    break

        if LOW_COUNT_FORCE_FILL_ENABLED and len(finalized) < target_count:
            remaining = target_count - len(finalized)
            relaxed_fallback_questions = self._build_fallback_questions(
                context=context,
                chunks=chunks,
                target_count=max(remaining * 3, target_count),
                question_types=(
                    question_types
                    if len(set(question_types or [])) > 1
                    else ["multiple_choice", "true_false"]
                ),
                difficulty=difficulty,
                bloom_levels=bloom_levels,
                relaxed_mode=True,
            )
            for candidate in relaxed_fallback_questions:
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                finalized.append(
                    self._enrich_question_metadata(
                        question=candidate,
                        chunk_map=chunk_map,
                        resource_map=resource_map,
                        score_map=score_map,
                        quality_score=self._score_question_quality(
                            candidate, chunk_map=chunk_map, score_map=score_map
                        ),
                    )
                )
                if len(finalized) >= target_count:
                    break

        if len(finalized) < target_count:
            medium_fill_questions = self._build_reinforcement_questions(
                context=context,
                chunks=chunks,
                target_count=target_count - len(finalized),
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            for candidate in medium_fill_questions:
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                finalized.append(
                    self._enrich_question_metadata(
                        question=candidate,
                        chunk_map=chunk_map,
                        resource_map=resource_map,
                        score_map=score_map,
                        quality_score=self._score_question_quality(
                            candidate, chunk_map=chunk_map, score_map=score_map
                        ),
                    )
                )
                if len(finalized) >= target_count:
                    break

        if not finalized:
            return [], base_message or "Không thể tạo câu hỏi hợp lệ từ lesson này."

        covered_chunk_count = len(
            {chunk_id for item in finalized for chunk_id in item.chunk_ids}
        )
        used_local_fallback = any(
            item.metadata.get("generation_mode") in {"local_fallback", "local_fill"}
            for item in finalized
        )
        average_quality_score = round(
            sum(float(item.metadata.get("quality_score", 0.0)) for item in finalized)
            / max(len(finalized), 1),
            4,
        )
        message = (
            base_message
            or f"Đã tạo {len(finalized)} câu hỏi bám trên {covered_chunk_count} chunk."
        )
        if "Điểm chất lượng" not in message:
            message = f"{message} Điểm chất lượng trung bình: {average_quality_score}."
        if used_local_fallback and "cục bộ" not in message.lower():
            message = f"{message} Hệ thống đã bổ sung thêm câu hỏi cục bộ để tăng độ phủ lesson."
        if len(finalized) < target_count:
            message = (
                f"{message} Hiện tạo được {len(finalized)}/{target_count} câu hỏi từ nội dung đủ tin cậy trong lesson."
            )
        return finalized, message

    def _round_robin_questions_by_chunk_order(
        self,
        *,
        questions: List[ValidatedLessonQuestion],
        preferred_chunk_order: List[str],
        chunk_map: Dict[str, Dict[str, Any]],
        score_map: Dict[str, float],
    ) -> List[ValidatedLessonQuestion]:
        buckets: Dict[str, List[ValidatedLessonQuestion]] = {
            chunk_id: [] for chunk_id in preferred_chunk_order
        }
        overflow: List[ValidatedLessonQuestion] = []
        for question in questions:
            primary_chunk_id = next(
                (chunk_id for chunk_id in question.chunk_ids if chunk_id in buckets),
                None,
            )
            if primary_chunk_id is None:
                overflow.append(question)
                continue
            buckets[primary_chunk_id].append(question)

        for bucket in buckets.values():
            bucket.sort(
                key=lambda item: self._score_question_quality(
                    item, chunk_map=chunk_map, score_map=score_map
                ),
                reverse=True,
            )
        overflow.sort(
            key=lambda item: self._score_question_quality(
                item, chunk_map=chunk_map, score_map=score_map
            ),
            reverse=True,
        )

        ordered: List[ValidatedLessonQuestion] = []
        progress = True
        while progress:
            progress = False
            for chunk_id in preferred_chunk_order:
                bucket = buckets.get(chunk_id) or []
                if not bucket:
                    continue
                ordered.append(bucket.pop(0))
                progress = True

        ordered.extend(overflow)
        for chunk_id in preferred_chunk_order:
            ordered.extend(buckets.get(chunk_id) or [])
        return ordered

    def _enrich_question_metadata(
        self,
        *,
        question: ValidatedLessonQuestion,
        chunk_map: Dict[str, Dict[str, Any]],
        resource_map: Dict[str, Dict[str, Any]],
        score_map: Dict[str, float],
        quality_score: float,
    ) -> ValidatedLessonQuestion:
        metadata = dict(question.metadata or {})
        source_page_numbers = sorted(
            {
                page_number
                for chunk_id in question.chunk_ids
                if chunk_id in chunk_map
                for page_number in [
                    self.lesson_chunk_service._resolve_page_number(chunk_map[chunk_id])
                ]
                if isinstance(page_number, int)
            }
        )
        source_chunk_indexes = sorted(
            {
                int(chunk_map[chunk_id].get("chunk_index", 0))
                for chunk_id in question.chunk_ids
                if chunk_id in chunk_map
            }
        )
        source_resource_ids = sorted(
            {
                str(chunk_map[chunk_id]["resource_id"])
                for chunk_id in question.chunk_ids
                if chunk_id in chunk_map and chunk_map[chunk_id].get("resource_id")
            }
        )
        source_resource_titles = [
            str(resource_map[resource_id].get("title") or "").strip()
            for resource_id in source_resource_ids
            if resource_id in resource_map
            and str(resource_map[resource_id].get("title") or "").strip()
        ]
        source_resource_sources = [
            str(resource_map[resource_id].get("source") or "").strip()
            for resource_id in source_resource_ids
            if resource_id in resource_map
            and str(resource_map[resource_id].get("source") or "").strip()
        ]
        source_scores = {
            chunk_id: round(float(score_map.get(chunk_id, 0.0)), 4)
            for chunk_id in question.chunk_ids
            if chunk_id in score_map
        }

        if (
            "question_focus" not in metadata
            or not str(metadata.get("question_focus") or "").strip()
        ):
            metadata["question_focus"] = self._extract_question_focus(question.question)
        if source_page_numbers:
            metadata.setdefault("source_page_number", source_page_numbers[0])
            metadata["source_page_numbers"] = source_page_numbers
        if source_chunk_indexes:
            metadata.setdefault("source_chunk_index", source_chunk_indexes[0])
            metadata["source_chunk_indexes"] = source_chunk_indexes
        if source_resource_ids:
            metadata.setdefault("source_resource_id", source_resource_ids[0])
            metadata["source_resource_ids"] = source_resource_ids
        if source_resource_titles:
            metadata.setdefault("source_resource_title", source_resource_titles[0])
            metadata["source_resource_titles"] = source_resource_titles
        if source_resource_sources:
            metadata["source_resource_sources"] = source_resource_sources
        if source_scores:
            metadata.setdefault("source_score", max(source_scores.values()))
            metadata["source_scores"] = source_scores
        metadata["quality_score"] = round(float(quality_score), 4)
        metadata["confidence_score"] = self._compute_confidence_score(
            question=question,
            quality_score=quality_score,
            max_chunk_score=max(source_scores.values(), default=0.0),
        )
        metadata["generation_source"] = str(
            metadata.get("generation_source")
            or metadata.get("generation_mode")
            or "llm"
        )
        metadata["tracked_bloom_level"] = question.bloom_level
        metadata["tracked_difficulty"] = question.difficulty
        metadata.setdefault(
            "reasoning_note", "Question grounded on recommended lesson chunk(s)."
        )

        return ValidatedLessonQuestion(
            question_type=question.question_type,
            question=question.question,
            correct_answer=question.correct_answer,
            distractors=question.distractors,
            explanation=question.explanation,
            difficulty=question.difficulty,
            bloom_level=question.bloom_level,
            chunk_ids=question.chunk_ids,
            metadata=metadata,
        )

    def _score_question_quality(
        self,
        question: ValidatedLessonQuestion,
        *,
        chunk_map: Dict[str, Dict[str, Any]],
        score_map: Dict[str, float],
    ) -> float:
        score = 0.0
        normalized_question = self._normalize_text(question.question)
        normalized_answer = self._normalize_text(question.correct_answer)
        source_excerpt = str(question.metadata.get("source_excerpt") or "").strip()
        question_focus = str(
            question.metadata.get("question_focus")
            or self._extract_question_focus(question.question)
        ).strip()
        max_chunk_score = max(
            (
                float(score_map.get(chunk_id, 0.0))
                for chunk_id in question.chunk_ids
                if chunk_id in score_map
            ),
            default=0.0,
        )

        score += max_chunk_score * 2.4
        score += min(len(question.chunk_ids), 2) * 0.2

        if 40 <= len(question.question.strip()) <= 220:
            score += 0.8
        elif len(question.question.strip()) < 28:
            score -= 0.8
        else:
            score += 0.2

        if 25 <= len(question.explanation.strip()) <= 240:
            score += 0.45
        elif len(question.explanation.strip()) < 12:
            score -= 0.4

        if 70 <= len(source_excerpt) <= 260:
            score += 0.75
        elif len(source_excerpt) < 45:
            score -= 0.65

        if question_focus:
            score += 0.35
            if self._normalize_text(question_focus) in self._AMBIGUOUS_TERMS:
                score -= 0.3

        if question.question_type == "multiple_choice":
            unique_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            if len(unique_choices) == 4:
                score += 0.55
            if all(
                3 <= len(str(item).strip()) <= 80
                for item in [question.correct_answer, *question.distractors]
            ):
                score += 0.2
        elif question.question_type == "short_answer":
            if len(question.correct_answer.strip()) >= 18:
                score += 0.35
        elif question.question_type == "true_false":
            score += 0.1

        if (
            normalized_question
            and normalized_answer
            and normalized_answer in normalized_question
        ):
            score -= 0.9

        if any(chunk_id in chunk_map for chunk_id in question.chunk_ids):
            page_numbers = [
                self.lesson_chunk_service._resolve_page_number(chunk_map[chunk_id])
                for chunk_id in question.chunk_ids
                if chunk_id in chunk_map
            ]
            if any(
                isinstance(page_number, int) and page_number > 0
                for page_number in page_numbers
            ):
                score += 0.2

        return round(score, 4)

    def _compute_confidence_score(
        self,
        *,
        question: ValidatedLessonQuestion,
        quality_score: float,
        max_chunk_score: float,
    ) -> float:
        normalized_quality = max(0.0, min(1.0, float(quality_score) / 5.0))
        normalized_chunk = max(0.0, min(1.0, float(max_chunk_score)))
        coverage = max(0.0, min(1.0, len(question.chunk_ids) / 2.0))
        distractor_quality = 0.0
        if question.question_type == "multiple_choice":
            unique_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            distractor_quality = max(0.0, min(1.0, len(unique_choices) / 4.0))
        elif question.question_type == "short_answer":
            distractor_quality = 0.7
        else:
            distractor_quality = 0.6
        weighted = (
            QUESTION_CONFIDENCE_BASELINE
            + normalized_quality * 0.42
            + normalized_chunk * 0.24
            + coverage * 0.18
            + distractor_quality * 0.16
        )
        return round(max(0.0, min(1.0, weighted)), 4)

    @staticmethod
    def _resolve_adaptive_difficulty(
        *,
        requested_difficulty: str,
        mastery: float | None,
        success_rate: float | None,
        metadata: Dict[str, Any],
    ) -> str:
        if mastery is None:
            mastery = metadata.get("mastery") if isinstance(metadata, dict) else None
        if success_rate is None:
            success_rate = (
                metadata.get("success_rate") if isinstance(metadata, dict) else None
            )
        return QuestionTemplateService.resolve_difficulty_from_progress(
            requested_difficulty=requested_difficulty,
            mastery=mastery,
            success_rate=success_rate,
        )

    def _extract_question_focus(self, question_text: str) -> str:
        quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", question_text or "")
        for left, right in quoted:
            phrase = (left or right).strip()
            if phrase:
                return phrase
        normalized = self._normalize_text(question_text)
        for token in re.findall(r"\b[a-z][a-z0-9_]{3,}\b", normalized):
            if token not in self._FALLBACK_STOP_WORDS:
                return token
        return ""

    def _question_signature(self, question: ValidatedLessonQuestion) -> str:
        stem = self._normalize_text(question.question)
        answer = self._normalize_text(question.correct_answer)
        if not stem:
            return ""
        return f"{stem}::{answer}"

    @staticmethod
    def _determine_generation_mode(questions: List[ValidatedLessonQuestion]) -> str:
        if not questions:
            return "empty"
        generation_modes = {
            str(question.metadata.get("generation_mode") or "llm")
            for question in questions
        }
        if generation_modes <= {"local_fallback", "local_fill", "existing_reuse"}:
            return "local_fallback"
        if (
            "local_fallback" in generation_modes
            or "local_fill" in generation_modes
            or "existing_reuse" in generation_modes
        ):
            return "hybrid"
        return "llm"

    def _log_generation_outcome(
        self,
        *,
        lesson_id: str,
        status: str,
        generation_mode: str,
        question_count: int,
        chunk_count: int,
        covered_chunk_count: int,
        llm_error: str | None,
        message: str,
    ) -> None:
        extra_error = f" | llm_error={llm_error}" if llm_error else ""
        logger.info(
            "lesson_question_generation | lesson_id=%s | status=%s | mode=%s | questions=%s | chunks=%s | covered_chunks=%s | message=%s%s",
            lesson_id,
            status,
            generation_mode,
            question_count,
            chunk_count,
            covered_chunk_count,
            message,
            extra_error,
        )

    def _resolve_recommendation(
        self, lesson_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id)
        if recommendation:
            return recommendation

        lesson = context.get("lesson") or self.lesson_repository.get(lesson_id)
        if not lesson:
            return None

        chunk_ids = lesson.get("recommended_chunk_ids") or []
        if not chunk_ids:
            return None

        resource_ids = lesson.get("recommended_resource_ids") or []
        fallback_payload = {
            "subject_id": context["subject"]["_id"],
            "chapter_id": context["chapter"]["_id"],
            "lesson_id": lesson["_id"],
            "chunk_ids": list(chunk_ids),
            "resource_ids": list(resource_ids),
            "selection_strategy": "lesson_document_fallback_v1",
            "metadata": {
                "source": "lesson_document_fallback",
                "selected_count": len(chunk_ids),
            },
        }
        return self.recommendation_repository.upsert_for_lesson(
            lesson_id, fallback_payload
        )

    def _load_generation_scope(
        self,
        *,
        lesson_id: str,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        if not recommendation:
            raise ValueError(
                "Lesson has no recommended chunks. Generate recommended chunks first."
            )

        chunk_ids = [str(item) for item in recommendation.get("chunk_ids", [])]
        if not chunk_ids:
            raise ValueError("Lesson recommendation does not contain chunk ids.")

        chunks = self.chunk_repository.get_by_ids(chunk_ids)
        if not chunks:
            raise ValueError("Recommended chunks could not be loaded.")

        if len(chunks) != len(chunk_ids):
            chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
            chunks = [chunk_map[item] for item in chunk_ids if item in chunk_map]
        return recommendation, chunk_ids, chunks

    def _run_generation(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ):
        resource_ids = [
            str(chunk.get("resource_id"))
            for chunk in chunks
            if chunk.get("resource_id")
        ]
        resources = (
            self.resource_repository.get_many(resource_ids) if resource_ids else []
        )
        resource_map = {
            str(resource["_id"]): resource
            for resource in resources
            if resource.get("_id")
        }
        chunk_payload = [
            {
                "chunk_id": str(chunk["_id"]),
                "resource_id": str(chunk["resource_id"]),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "page_number": self.lesson_chunk_service._resolve_page_number(chunk),
                "resource_title": str(
                    resource_map.get(str(chunk["resource_id"]), {}).get("title") or ""
                ),
                "resource_source": str(
                    resource_map.get(str(chunk["resource_id"]), {}).get("source") or ""
                ),
                "score": float(
                    context.get("recommendation_scores", {}).get(str(chunk["_id"]), 0.0)
                    if isinstance(context.get("recommendation_scores"), dict)
                    else 0.0
                ),
                "content": str(chunk.get("content") or ""),
            }
            for chunk in chunks
        ]
        return self.question_llm_service.generate(
            context=context,
            chunk_payload=chunk_payload,
            allowed_chunk_ids=chunk_ids,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
        )

    def _refresh_recommendation(
        self,
        *,
        lesson_id: str,
        metadata: Dict[str, Any],
        max_chunks: int | None = None,
    ) -> Dict[str, Any] | None:
        try:
            refreshed = self.lesson_chunk_service.recommend_chunks(
                lesson_id=lesson_id,
                max_chunks=max_chunks or QUESTION_GENERATION_REFRESH_MAX_CHUNKS,
                selection_strategy="local_semantic_lexical_refresh_v2",
                enable_diversity_reranking=True,
                diversity_lambda=None,
                resource_ids=[],
                metadata={
                    **metadata,
                    "trigger": "question_generation_retry",
                },
            )
            self.lesson_repository.update(
                lesson_id,
                {
                    "recommended_chunk_ids": refreshed.get("chunk_ids", []),
                    "recommended_resource_ids": refreshed.get("resource_ids", []),
                },
            )
            return self.recommendation_repository.get_by_lesson(lesson_id)
        except Exception:
            return None

    def _build_fallback_questions(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        relaxed_mode: bool = False,
    ) -> List[ValidatedLessonQuestion]:
        lesson_title = str(context["lesson"].get("title") or "this lesson").strip()
        keyword_profile = self._build_keyword_profile(context)
        strict_keywords = keyword_profile["strict"]
        broad_keywords = keyword_profile["broad"]
        selected_types = question_types or ["multiple_choice"]
        selected_bloom_levels = bloom_levels or ["understand"]
        chunk_candidates = []
        for chunk in chunks:
            excerpt = self._select_excerpt(
                content=str(chunk.get("content") or ""),
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if not excerpt:
                continue
            score = self._score_excerpt_for_fallback(
                excerpt=excerpt,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if score <= 0:
                continue
            chunk_candidates.append((score, chunk, excerpt))
        chunk_candidates.sort(key=lambda item: item[0], reverse=True)
        strong_candidates = [item for item in chunk_candidates if item[0] >= 1.25]
        if strong_candidates:
            chunk_candidates = strong_candidates
        if not chunk_candidates:
            for chunk in chunks:
                excerpt = self._select_excerpt(
                    content=str(chunk.get("content") or ""),
                    strict_keywords=strict_keywords,
                    broad_keywords=broad_keywords,
                )
                if excerpt:
                    chunk_candidates.append((0.0, chunk, excerpt))

        questions: List[ValidatedLessonQuestion] = []
        for index, (excerpt_score, chunk, excerpt) in enumerate(chunk_candidates):
            if len(questions) >= target_count:
                break
            question_type = selected_types[index % len(selected_types)]
            bloom_level = selected_bloom_levels[index % len(selected_bloom_levels)]
            question = self._build_fallback_question(
                question_type=question_type,
                lesson_title=lesson_title,
                excerpt=excerpt,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
                relaxed_mode=relaxed_mode,
            )
            if not question:
                continue
            if not relaxed_mode and float(excerpt_score) < 1.0:
                continue
            questions.append(
                ValidatedLessonQuestion(
                    question_type=question_type,
                    question=question["question"],
                    correct_answer=question["correct_answer"],
                    distractors=question["distractors"],
                    explanation=question.get("explanation")
                    or f"Câu hỏi được tạo trực tiếp từ đoạn trích của bài học '{lesson_title}'.",
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    chunk_ids=[str(chunk["_id"])],
                    metadata={
                        "source_excerpt": excerpt,
                        "question_focus": question.get("focus_term") or "",
                        "fallback_excerpt_score": round(float(excerpt_score), 4),
                        "reasoning_note": "Generated by deterministic local fallback from recommended chunk.",
                        "generation_mode": "local_fallback",
                    },
                )
            )
        return questions

    def _build_reinforcement_questions(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        target_count: int,
        difficulty: str,
        bloom_levels: List[str],
    ) -> List[ValidatedLessonQuestion]:
        if target_count <= 0:
            return []

        lesson_title = str(context["lesson"].get("title") or "this lesson").strip()
        keyword_profile = self._build_keyword_profile(context)
        strict_keywords = keyword_profile["strict"]
        broad_keywords = keyword_profile["broad"]
        selected_bloom_levels = bloom_levels or ["understand"]

        chunk_candidates = []
        for chunk in chunks:
            excerpt = self._select_excerpt(
                content=str(chunk.get("content") or ""),
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if not excerpt:
                continue
            score = self._score_excerpt_for_fallback(
                excerpt=excerpt,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if score <= 0:
                continue
            chunk_candidates.append((score, chunk, excerpt))

        chunk_candidates.sort(key=lambda item: item[0], reverse=True)
        questions: List[ValidatedLessonQuestion] = []
        true_false_budget = max(
            1,
            int(round(float(target_count) * max(0.0, min(1.0, REINFORCEMENT_TRUE_FALSE_RATIO)))),
        )
        used_true_false = 0
        focus_usage: Dict[str, int] = {}
        max_per_focus = 2 if target_count >= 5 else 1
        for index, (_, chunk, excerpt) in enumerate(chunk_candidates):
            if len(questions) >= target_count:
                break

            excerpt_norm = self._normalize_text(excerpt)
            focus = self._find_focus_term(
                excerpt=excerpt_norm,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            ) or self._find_specific_focus_term(
                excerpt=excerpt_norm,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if not focus:
                continue
            normalized_focus = self._normalize_term_key(focus)
            if focus_usage.get(normalized_focus, 0) >= max_per_focus:
                continue

            question_type = (
                "true_false"
                if (index % 3 == 2 and used_true_false < true_false_budget)
                else "multiple_choice"
            )
            bloom_level = selected_bloom_levels[index % len(selected_bloom_levels)]

            if question_type == "multiple_choice":
                distractors = self._build_distractors(
                    answer=focus,
                    excerpt=excerpt_norm,
                    keywords=strict_keywords or broad_keywords,
                    category=self._classify_term(focus),
                    relaxed_mode=False,
                )
                if len(distractors) < 3:
                    distractors = self._build_distractors(
                        answer=focus,
                        excerpt=excerpt_norm,
                        keywords=strict_keywords or broad_keywords,
                        category=self._classify_term(focus),
                        relaxed_mode=True,
                    )
                if len(distractors) < 3:
                    continue
                mc_templates = [
                    f"Theo đoạn trích của bài '{lesson_title}', thuật ngữ nào được nhắc đến như một trọng tâm nội dung?",
                    f"Dựa trên đoạn trích của bài '{lesson_title}', khái niệm nào xuất hiện trực tiếp trong nội dung?",
                    f"Theo nội dung bài '{lesson_title}', đáp án nào khớp nhất với thuật ngữ đã nêu trong đoạn trích?",
                ]
                question_text = mc_templates[index % len(mc_templates)]
                correct_answer = focus
                distractors = distractors[:3]
                explanation = (
                    f"Đoạn trích có nhắc trực tiếp '{focus}', vì vậy đây là đáp án phù hợp nhất trong các lựa chọn."
                )
            else:
                statement = self._clean_true_false_statement(
                    self._summarize_excerpt(excerpt=excerpt, focus_term=focus)
                )
                if (
                    len(statement) < 20
                    or not re.match(r"^[A-Za-z].{18,}$", statement)
                    or statement.startswith("]")
                    or "range(" in statement
                    or "#" in statement
                    or len(statement) > REINFORCEMENT_STATEMENT_MAX_LEN
                    or statement.count("(") >= 2
                    or statement.count("[") >= 2
                    or statement.count("{") >= 1
                ):
                    continue
                tf_templates = [
                    f"Phát biểu sau là đúng hay sai theo đoạn trích của bài '{lesson_title}'? \"{statement}\"",
                    f"Theo nội dung bài '{lesson_title}', mệnh đề sau đúng hay sai? \"{statement}\"",
                ]
                question_text = tf_templates[index % len(tf_templates)]
                correct_answer = "True"
                distractors = ["False"]
                explanation = (
                    "Phát biểu được giữ từ nội dung chunk đã chọn, nên được xem là đúng theo ngữ cảnh bài học."
                )
                used_true_false += 1

            questions.append(
                ValidatedLessonQuestion(
                    question_type=question_type,
                    question=question_text,
                    correct_answer=correct_answer,
                    distractors=distractors,
                    explanation=explanation,
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    chunk_ids=[str(chunk["_id"])],
                    metadata={
                        "source_excerpt": excerpt,
                        "question_focus": focus,
                        "reasoning_note": "Generated by medium-quality reinforcement fill from lesson chunk.",
                        "generation_mode": "local_fill",
                    },
                )
            )
            focus_usage[normalized_focus] = focus_usage.get(normalized_focus, 0) + 1

        return questions

    def _build_validation_from_fallback(
        self,
        *,
        questions: List[ValidatedLessonQuestion],
        message: str,
        status: str = "ok",
    ):
        return type(
            "FallbackValidationPayload",
            (),
            {
                "status": status,
                "message": message,
                "questions": questions,
                "errors": [],
            },
        )()

    def _build_template_validation(
        self,
        *,
        lesson_title: str,
        chunks: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        chunk_ids: List[str],
        chunk_text_by_id: Dict[str, str],
    ):
        template_candidates = self.question_template_service.build_candidates(
            lesson_title=lesson_title,
            chunks=chunks,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
            max_per_chunk=QUESTION_DIVERSITY_MAX_PER_CHUNK,
        )
        return self.question_validation_service.validate_candidates(
            candidates=template_candidates,
            allowed_chunk_ids=chunk_ids,
            chunk_text_by_id=chunk_text_by_id,
            default_difficulty=difficulty,
            default_bloom_levels=bloom_levels,
        )

    def _build_existing_fill_questions(
        self,
        *,
        existing_questions: List[Dict[str, Any]],
        target_count: int,
    ) -> List[ValidatedLessonQuestion]:
        if target_count <= 0:
            return []

        filled: List[ValidatedLessonQuestion] = []
        for item in existing_questions:
            if len(filled) >= target_count:
                break
            question_text = str(item.get("question") or "").strip()
            correct_answer = str(item.get("correct_answer") or "").strip()
            explanation = str(item.get("explanation") or "").strip()
            question_type = str(item.get("question_type") or "multiple_choice").strip()
            difficulty = str(item.get("difficulty") or "beginner").strip()
            bloom_level = str(item.get("bloom_level") or "understand").strip()
            chunk_ids = [str(chunk_id) for chunk_id in item.get("chunk_ids", []) if str(chunk_id)]
            raw_distractors = item.get("distractors") or []
            distractors = [
                str(choice).strip()
                for choice in raw_distractors
                if str(choice).strip()
            ]
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}

            if not question_text or not correct_answer or not explanation or not chunk_ids:
                continue
            if question_type not in {"multiple_choice", "short_answer", "true_false"}:
                continue
            if question_type == "multiple_choice" and len(distractors) < 2:
                continue
            if question_type == "true_false":
                if correct_answer not in {"True", "False"}:
                    continue
                distractors = ["False" if correct_answer == "True" else "True"]

            filled.append(
                ValidatedLessonQuestion(
                    question_type=question_type,
                    question=question_text,
                    correct_answer=correct_answer,
                    distractors=distractors[:3],
                    explanation=explanation,
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    chunk_ids=chunk_ids,
                    metadata={
                        **metadata,
                        "generation_mode": "existing_reuse",
                        "reasoning_note": "Reused from existing question bank to maintain minimum target count.",
                    },
                )
            )

        return filled

    def _build_existing_or_insufficient_response(
        self,
        *,
        lesson_id: str,
        chunk_ids: List[str],
        existing_count: int,
        default_message: str,
        source_stats: Dict[str, int] | None = None,
        filtered_count: int = 0,
    ) -> Dict[str, Any]:
        stats = source_stats or {
            "template": 0,
            "llm": 0,
            "local_fallback": 0,
            "existing_reuse": 0,
        }
        if existing_count > 0:
            stats = {**stats, "existing_reuse": max(stats.get("existing_reuse", 0), existing_count)}
            return {
                "lesson_id": lesson_id,
                "status": "reused_existing",
                "generated_count": 0,
                "saved_count": 0,
                "question_ids": [],
                "chunks_used": chunk_ids,
                "insufficient_data": False,
                "reused_existing": True,
                "existing_count": existing_count,
                "sources": stats,
                "filtered_count": filtered_count,
                "message": self._build_llm_fallback_message(
                    f"AI hiện chưa sinh được bộ câu hỏi mới. Hệ thống đang dùng lại {existing_count} câu hỏi đã tạo trước đó cho bài học này."
                ),
            }
        return {
            "lesson_id": lesson_id,
            "status": "insufficient_context",
            "generated_count": 0,
            "saved_count": 0,
            "question_ids": [],
            "chunks_used": chunk_ids,
            "insufficient_data": True,
            "reused_existing": False,
            "existing_count": 0,
            "sources": stats,
            "filtered_count": filtered_count,
            "message": self._build_llm_fallback_message(default_message),
        }

    def _build_llm_fallback_message(self, default_message: str) -> str:
        raw_error = (self.llm_client.get_last_error() or "").lower()
        if not raw_error:
            return default_message
        if (
            "resource_exhausted" in raw_error
            or "quota exceeded" in raw_error
            or "429" in raw_error
        ):
            return (
                "Dịch vụ AI đang vượt giới hạn quota tạm thời. "
                "Hệ thống đã chuyển sang phương án dự phòng cục bộ nếu có thể. "
                "Bạn có thể thử lại sau ít phút nếu muốn có bộ câu hỏi AI đầy đủ hơn."
            )
        if "not available" in raw_error:
            return (
                "Dịch vụ AI tạo câu hỏi hiện chưa sẵn sàng. "
                "Hệ thống sẽ dùng dữ liệu cục bộ khi có thể."
            )
        return default_message

    @staticmethod
    def _select_excerpt(
        *, content: str, strict_keywords: List[str], broad_keywords: List[str]
    ) -> str:
        normalized = re.sub(r"\s+", " ", content or "").strip()
        if not normalized:
            return ""
        segments = re.split(r"(?<=[\.\!\?])\s+", normalized)
        scored_segments = []
        for segment in segments:
            if 60 <= len(segment) <= 260:
                score = (
                    LessonScopedQuestionGenerationService._score_excerpt_for_fallback(
                        excerpt=segment,
                        strict_keywords=strict_keywords,
                        broad_keywords=broad_keywords,
                    )
                )
                if score > 0:
                    scored_segments.append((score, segment))
        if scored_segments:
            scored_segments.sort(key=lambda item: item[0], reverse=True)
            return scored_segments[0][1]
        for segment in segments:
            if 60 <= len(segment) <= 240:
                return segment
        if len(normalized) <= 240:
            return normalized
        cutoff = normalized[:240].rsplit(" ", 1)[0].strip()
        return f"{cutoff}..."

    @classmethod
    def _build_keyword_profile(cls, context: Dict[str, Any]) -> Dict[str, List[str]]:
        strict_sources = [
            str(context["lesson"].get("title") or ""),
            *[str(item) for item in context["lesson"].get("keywords", [])],
        ]
        broad_sources = [
            *strict_sources,
            str(context["lesson"].get("summary") or ""),
        ]
        return {
            "strict": cls._collect_keywords(strict_sources, strict_mode=True),
            "broad": cls._collect_keywords(broad_sources, strict_mode=False),
        }

    @classmethod
    def _collect_keywords(cls, sources: List[str], *, strict_mode: bool) -> List[str]:
        keywords: List[str] = []
        seen = set()
        alias_map = cls._STRICT_CONCEPT_ALIASES if strict_mode else cls._CONCEPT_ALIASES
        for term in sources:
            normalized = cls._normalize_text(term)
            for phrase, aliases in alias_map.items():
                if phrase in normalized:
                    phrase_key = cls._normalize_text(phrase)
                    if phrase_key not in seen:
                        seen.add(phrase_key)
                        keywords.append(phrase_key)
                    for alias in aliases:
                        alias_key = cls._normalize_text(alias)
                        if alias_key not in seen:
                            seen.add(alias_key)
                            keywords.append(alias_key)
            for token in re.findall(r"\b[a-z][a-z0-9_]{2,}\b", normalized):
                if token in cls._FALLBACK_STOP_WORDS or token in seen:
                    continue
                if not cls._is_domain_term(token):
                    continue
                seen.add(token)
                keywords.append(token)
        return keywords

    def _build_fallback_question(
        self,
        *,
        question_type: str,
        lesson_title: str,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
        relaxed_mode: bool = False,
    ) -> Dict[str, Any] | None:
        excerpt_lower = self._normalize_text(excerpt)
        focus_term = self._find_focus_term(
            excerpt=excerpt_lower,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )
        if focus_term in self._AMBIGUOUS_TERMS:
            focus_term = self._find_specific_focus_term(
                excerpt=excerpt_lower,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
        if not focus_term and relaxed_mode:
            focus_term = self._find_specific_focus_term(
                excerpt=excerpt_lower,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            ) or self._first_meaningful_word(excerpt_lower)
        if not focus_term:
            return None
        if (
            not relaxed_mode
            and focus_term in self._AMBIGUOUS_TERMS
            and not self._has_context_anchor(excerpt=excerpt_lower, focus_term=focus_term)
        ):
            return None
        category = self._classify_term(focus_term)
        if question_type == "multiple_choice":
            answer = focus_term or self._first_meaningful_word(excerpt)
            if not answer:
                return None
            distractors = self._build_distractors(
                answer=answer,
                excerpt=excerpt_lower,
                keywords=strict_keywords or broad_keywords,
                category=category,
                relaxed_mode=relaxed_mode,
            )
            if len(distractors) < 3:
                return None
            return {
                "question": self._build_multiple_choice_prompt(
                    lesson_title=lesson_title,
                    category=category,
                    focus_term=answer,
                ),
                "correct_answer": answer,
                "distractors": distractors[:3],
                "focus_term": answer,
                "explanation": (
                    f"Đoạn trích nêu trực tiếp khái niệm '{answer}', vì vậy đây là đáp án phù hợp nhất."
                ),
            }
        if question_type == "true_false":
            statement = self._clean_true_false_statement(
                self._summarize_excerpt(excerpt=excerpt, focus_term=focus_term)
            )
            if len(statement) < 20:
                return None
            return {
                "question": f"Phát biểu sau là đúng hay sai theo đoạn trích của bài '{lesson_title}'? \"{statement}\"",
                "correct_answer": "True",
                "distractors": ["False"],
                "focus_term": focus_term,
                "explanation": "Phát biểu được giữ nguyên từ đoạn trích nên được xem là đúng theo ngữ cảnh bài học.",
            }
        short_answer = self._summarize_excerpt(excerpt=excerpt, focus_term=focus_term)
        return {
            "question": self._build_short_answer_prompt(
                lesson_title=lesson_title,
                focus_term=focus_term,
            ),
            "correct_answer": short_answer,
            "distractors": [],
            "focus_term": focus_term,
            "explanation": (
                f"Câu trả lời tóm tắt trực tiếp câu/ý có chứa '{focus_term}' trong đoạn trích."
            ),
        }

    def _build_distractors(
        self,
        *,
        answer: str,
        excerpt: str,
        keywords: List[str],
        category: str,
        relaxed_mode: bool,
    ) -> List[str]:
        normalized_answer = answer.strip().lower()
        answer_category = self._classify_term(normalized_answer)
        contextual_terms = self._extract_contextual_terms(
            excerpt=excerpt,
            keywords=keywords,
            category=answer_category,
            limit=12,
        )
        candidates = list(contextual_terms)
        candidates.extend(self._CATEGORY_POOLS.get(answer_category, []))
        if answer_category != category:
            candidates.extend(self._CATEGORY_POOLS.get(category, []))
        candidates.extend(
            item for item in keywords if item.strip().lower() != normalized_answer
        )
        candidates.extend(self._FALLBACK_DISTRACTORS)
        unique: List[str] = []
        seen = {normalized_answer, self._normalize_term_key(normalized_answer)}
        for item in candidates:
            cleaned = item.strip()
            key = cleaned.lower()
            stem_key = self._normalize_term_key(key)
            if len(cleaned) < 3 or key in self._FALLBACK_STOP_WORDS:
                continue
            if key in seen or stem_key in seen:
                continue
            if not relaxed_mode and key in self._WEAK_DISTRACTOR_TERMS:
                continue
            if self._classify_term(cleaned) == answer_category and cleaned.lower() == normalized_answer:
                continue
            if not relaxed_mode and self._classify_term(cleaned) == "general":
                continue
            seen.add(key)
            seen.add(stem_key)
            unique.append(cleaned)
        return unique

    def _find_specific_focus_term(
        self,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> str:
        candidates = self._extract_contextual_terms(
            excerpt=excerpt,
            keywords=strict_keywords + broad_keywords,
            category="general",
            limit=10,
        )
        for token in candidates:
            if token in self._AMBIGUOUS_TERMS or token in self._WEAK_DISTRACTOR_TERMS:
                continue
            if not self._is_domain_term(token):
                continue
            return token
        return ""

    def _extract_contextual_terms(
        self,
        *,
        excerpt: str,
        keywords: List[str],
        category: str,
        limit: int,
    ) -> List[str]:
        tokens = re.findall(r"\b[a-z][a-z0-9_]{2,}\b", self._normalize_text(excerpt))
        scored: List[tuple[float, str]] = []
        for token in tokens:
            if token in self._FALLBACK_STOP_WORDS or token in self._WEAK_DISTRACTOR_TERMS:
                continue
            token_category = self._classify_term(token)
            if token_category == "general" and token not in keywords:
                continue
            score = 0.0
            if token_category == category:
                score += 1.5
            elif token_category != "general":
                score += 0.5
            if token in keywords:
                score += 0.8
            if len(token) >= 5:
                score += 0.2
            scored.append((score, token))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: List[str] = []
        seen: set[str] = set()
        for _, token in scored:
            key = self._normalize_term_key(token)
            if key in seen:
                continue
            seen.add(key)
            results.append(token)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _normalize_term_key(value: str) -> str:
        token = re.sub(r"[^a-z0-9_]+", "", str(value or "").lower())
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("es") and len(token) > 4:
            return token[:-2]
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    @classmethod
    def _first_meaningful_word(cls, text: str) -> str:
        for token in re.findall(r"\b[a-z][a-z0-9_]{2,}\b", cls._normalize_text(text)):
            if (
                len(token) >= 4
                and token.isalpha()
                and token not in cls._FALLBACK_STOP_WORDS
            ):
                return token
        return ""

    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_text.lower()).strip()

    @classmethod
    def _is_domain_term(cls, token: str) -> bool:
        normalized = cls._normalize_text(token)
        if not normalized or normalized in cls._FALLBACK_STOP_WORDS:
            return False
        if normalized in cls._EXPLICIT_DOMAIN_TERMS:
            return True
        category = cls._classify_term(normalized)
        if category != "general":
            return True
        return bool(re.search(r"\b(arr|list|dict|tuple|set|func|oper|type|bool|loop)\w*\b", normalized))

    @classmethod
    def _find_focus_term(
        cls,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> str:
        for keyword_pool in (strict_keywords, broad_keywords):
            for keyword in sorted(keyword_pool, key=len, reverse=True):
                if keyword in cls._FALLBACK_STOP_WORDS:
                    continue
                if re.search(rf"\b{re.escape(keyword)}\b", excerpt):
                    if keyword in {"dictionary", "dictionaries"}:
                        return "dict"
                    if keyword in {"lists"}:
                        return "list"
                    if keyword in {"variables"}:
                        return "variable"
                    if keyword in {"operators"}:
                        return "operator"
                    return keyword
        return ""

    @classmethod
    def _has_context_anchor(cls, *, excerpt: str, focus_term: str) -> bool:
        if focus_term in {"value", "values", "item", "items", "key", "keys"}:
            anchors = {
                "dict",
                "dictionary",
                "dictionaries",
                "list",
                "lists",
                "tuple",
                "tuples",
            }
            return any(
                re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors
            )
        if focus_term in {"type", "types"}:
            anchors = {"variable", "variables", "string", "integer", "float", "boolean"}
            return any(
                re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors
            )
        if focus_term == "data":
            anchors = {
                "list",
                "dict",
                "dictionary",
                "variable",
                "operator",
                "string",
                "float",
                "integer",
            }
            return any(
                re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors
            )
        return True

    @classmethod
    def _score_excerpt_for_fallback(
        cls,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> float:
        normalized = cls._normalize_text(excerpt)
        if not normalized:
            return -1.0
        score = 0.0
        for pattern in cls._IRRELEVANT_EXCERPT_PATTERNS:
            if re.search(pattern, normalized):
                score -= 1.5
        strict_hits = 0
        for keyword in strict_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", normalized):
                strict_hits += 1
                score += 1.25 if len(keyword) <= 5 else 1.6
        for keyword in broad_keywords:
            if keyword in strict_keywords:
                continue
            if re.search(rf"\b{re.escape(keyword)}\b", normalized):
                score += 0.35 if len(keyword) <= 5 else 0.5
        if strict_hits >= 2:
            score += 0.8
        if ">>>" in excerpt or "def " in excerpt:
            score += 0.4
        if any(
            token in normalized
            for token in (
                "list",
                "dict",
                "dictionary",
                "variable",
                "operator",
                "string",
                "float",
                "integer",
            )
        ):
            score += 0.8
        if len(normalized) < 60:
            score -= 0.5
        return score

    @classmethod
    def _classify_term(cls, term: str) -> str:
        normalized = cls._normalize_text(term)
        if normalized in {
            "numpy",
            "ndarray",
            "array",
            "arrays",
            "matrix",
            "vector",
            "shape",
            "dtype",
            "ndim",
            "size",
        }:
            return "data_structure"
        if normalized in {
            "list",
            "dict",
            "dictionary",
            "tuple",
            "set",
            "keys",
            "values",
            "items",
        }:
            return "data_structure"
        if normalized in {
            "append",
            "sort",
            "split",
            "strip",
            "findall",
            "open",
            "read",
            "write",
            "reshape",
            "astype",
            "sum",
            "mean",
            "index",
            "slice",
            "slicing",
            "iterator",
            "iterators",
            "generator",
            "generators",
            "comprehension",
            "comprehensions",
        }:
            return "method"
        if normalized in {"string", "integer", "float", "boolean", "variable", "value"}:
            return "data_type"
        if normalized in {
            "operator",
            "arithmetic",
            "comparison",
            "logical",
            "expression",
            "assignment",
        }:
            return "operator"
        return "general"

    @staticmethod
    def _build_multiple_choice_prompt(
        *, lesson_title: str, category: str, focus_term: str
    ) -> str:
        if category == "data_structure":
            return f"Theo doan trich cua bai '{lesson_title}', cau truc du lieu nao duoc nhac den truc tiep?"
        if category == "method":
            return f"Theo doan trich cua bai '{lesson_title}', phuong thuc hoac ham nao xuat hien trong noi dung?"
        if category == "data_type":
            return f"Theo doan trich cua bai '{lesson_title}', kieu du lieu hoac khai niem nao duoc de cap?"
        if category == "operator":
            return f"Theo doan trich cua bai '{lesson_title}', toan tu hoac bieu thuc nao duoc nhac den?"
        return f"Theo doan trich cua bai '{lesson_title}', khai niem nao duoc nhac den truc tiep?"

    @staticmethod
    def _build_short_answer_prompt(*, lesson_title: str, focus_term: str) -> str:
        if focus_term:
            return f"Dựa trên đoạn trích của bài '{lesson_title}', hãy tóm tắt vai trò hoặc ý nghĩa của '{focus_term}'."
        return f"Dựa trên đoạn trích của bài '{lesson_title}', hãy nêu ý chính của nội dung này."

    @staticmethod
    def _summarize_excerpt(*, excerpt: str, focus_term: str) -> str:
        cleaned = re.sub(r"\s+", " ", excerpt or "").strip().strip('"')
        cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[\.\!\?])\s+", cleaned)
            if item.strip()
        ]
        if focus_term:
            for sentence in sentences:
                if focus_term in LessonScopedQuestionGenerationService._normalize_text(
                    sentence
                ):
                    snippet = sentence.split(",", 1)[0].strip()
                    if len(snippet) < 24:
                        snippet = sentence[:140].strip()
                    return snippet[:160].rstrip(" ,;:") + (
                        "..." if len(snippet) > 160 else ""
                    )
        if sentences:
            sentence = sentences[0]
            snippet = sentence.split(",", 1)[0].strip()
            if len(snippet) < 24:
                snippet = sentence[:140].strip()
            return snippet[:160].rstrip(" ,;:") + (
                "..." if len(snippet) > 160 else ""
            )
        snippet = cleaned.split(",", 1)[0].strip()
        if len(snippet) < 24:
            snippet = cleaned[:140].strip()
        return snippet[:160].rstrip(" ,;:") + ("..." if len(snippet) > 160 else "")

    @staticmethod
    def _clean_true_false_statement(statement: str) -> str:
        text = re.sub(r"\s+", " ", str(statement or "")).strip().strip('"')
        text = text.replace("``", "").replace("''", "")
        text = text.replace("â", "")
        # Remove duplicated adjacent words (for example: "NumPy NumPy").
        text = re.sub(r"\b([A-Za-z]{2,})\s+\1\b", r"\1", text, flags=re.IGNORECASE)
        text = re.sub(r"\[[^\]]*\]", "", text)
        text = re.sub(r"\{[^\}]*\}", "", text)
        text = re.sub(r"\([^\)]*#.*?\)", "", text)
        text = re.sub(r"\s*:\s*", ": ", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s*[:;]\s*$", "", text)
        text = text.strip(" -")
        return text


lesson_question_generation_service = LessonScopedQuestionGenerationService()
