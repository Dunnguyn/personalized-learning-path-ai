"""Lesson-scoped question generation and lesson question storage."""

from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
import hashlib
import json
import logging
import numpy as np
import os
import re
import time
from threading import Event, Lock
from typing import Any, Dict, List, Sequence
import unicodedata

from backend.app.ai_module import LessonQuestionLLMClient
from backend.app.repositories import (
    LessonRecommendedChunkRepository,
    LessonRepository,
    LessonQuestionRepository,
    QuestionSemanticMemoryRepository,
    ResourceChunkRepository,
    ResourceRepository,
)
from backend.app.services.embedding_service import cosine_similarity, embedding_service
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.lesson_assessment_sizing_service import (
    LessonAssessmentSizingResult,
    lesson_assessment_sizing_service,
)
from backend.app.services.concept_normalization_service import (
    concept_normalization_service,
)
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.prompt_builder import LessonScopedPromptBuilder
from backend.app.services.question_fallback_service import QuestionFallbackService
from backend.app.services.question_cross_verification_service import (
    question_cross_verification_service,
)
from backend.app.services.question_generation.fallback_fill import (
    build_distractors as fallback_build_distractors,
    build_fallback_question as fallback_build_question,
    classify_term as fallback_classify_term,
    extract_contextual_terms as fallback_extract_contextual_terms,
    find_focus_term as fallback_find_focus_term,
    find_specific_focus_term as fallback_find_specific_focus_term,
    has_context_anchor as fallback_has_context_anchor,
    score_excerpt_for_fallback as fallback_score_excerpt,
)
from backend.app.services.question_generation.llm_fill import (
    collect_additional_llm_questions as collect_llm_fill_questions,
)
from backend.app.services.question_generation.postprocess import (
    build_multiple_choice_prompt as build_mc_prompt,
    build_short_answer_prompt as build_sa_prompt,
    clean_true_false_statement as clean_tf_statement,
    summarize_excerpt as summarize_excerpt_text,
)
from backend.app.services.question_generation.scope_loader import (
    load_generation_scope as load_question_generation_scope,
)
from backend.app.services.question_generation.target_concepts import (
    collect_keywords as collect_target_keywords,
    question_matches_target_concepts as question_matches_targets,
    resolve_matched_target_concepts as resolve_target_matches,
)
from backend.app.services.question_generation.template_fill import (
    build_template_validation as build_template_fill_validation,
)
from backend.app.services.question_generation.dedup import (
    collect_excluded_question_signatures as collect_excluded_signatures,
    question_signature as build_question_signature,
    question_signature_from_parts as build_question_signature_from_parts,
)
from backend.app.services.question_llm_service import QuestionLLMService
from backend.app.services.question_template_service import QuestionTemplateService
from backend.app.services.question_validation_service import QuestionValidationService
from backend.app.services.question_validator import (
    LessonScopedQuestionValidator,
    ValidatedLessonQuestion,
)

logger = logging.getLogger(__name__)

LOW_COUNT_REGEN_RETRY_ENABLED = (
    os.getenv("LESSON_QUESTION_LOW_COUNT_RETRY_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
LOW_COUNT_REGEN_RETRY_DELAY_SECONDS = float(
    os.getenv("LESSON_QUESTION_LOW_COUNT_RETRY_DELAY_SECONDS", "0.25")
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
QUESTION_GENERATION_PREGEN_EXPAND_MIN_TARGET_COUNT = int(
    os.getenv("LESSON_QUESTION_PREGEN_EXPAND_MIN_TARGET_COUNT", "4")
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
QUESTION_SEMANTIC_DEDUP_ENABLED = (
    os.getenv("LESSON_QUESTION_SEMANTIC_DEDUP_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
QUESTION_SEMANTIC_DEDUP_THRESHOLD = float(
    os.getenv("LESSON_QUESTION_SEMANTIC_DEDUP_THRESHOLD", "0.92")
)
QUESTION_SEMANTIC_DEDUP_LOOKBACK = int(
    os.getenv("LESSON_QUESTION_SEMANTIC_DEDUP_LOOKBACK", "180")
)
PREFER_LLM_FILL_BEFORE_TEMPLATE_ENABLED = (
    os.getenv("LESSON_QUESTION_PREFER_LLM_FILL_BEFORE_TEMPLATE_ENABLED", "false")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
LLM_FILL_MAX_ATTEMPTS = int(
    os.getenv("LESSON_QUESTION_LLM_FILL_MAX_ATTEMPTS", "1")
)
DEGRADED_LOCAL_STATUSES = {
    "cooldown",
    "quota_exhausted",
    "empty_response",
    "invalid_response",
    "client_unavailable",
}
STANDARD_QUESTION_SET_KIND = "standard"
ADAPTIVE_QUESTION_SET_KIND = "adaptive"
ADAPTIVE_GENERATION_REASONS = {
    "adaptive_quiz_next",
    "reinforcement_quiz",
    "adaptive_quiz_attempt",
}


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
        "classes",
        "boolean",
    ]
    _WEAK_DISTRACTOR_TERMS = {
        "module",
        "class",
        "value",
        "values",
        "answer",
        "answers",
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
        "necessarily",
        "obvious",
        "easier",
        "understand",
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
        "class",
        "classes",
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
        self.question_repository = LessonQuestionRepository()
        self.question_semantic_memory_repository = QuestionSemanticMemoryRepository()
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
        self._inflight_generation_lock = Lock()
        self._inflight_generation_requests: Dict[str, Dict[str, Any]] = {}

        self.recommendation_repository.ensure_indexes()
        self.resource_repository.ensure_indexes()
        self.question_repository.ensure_indexes()
        self.question_semantic_memory_repository.ensure_indexes()

    def generate_questions_for_lesson(
        self,
        *,
        lesson_id: str,
        target_count: int | None,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        allow_llm: bool,
        mastery: float | None,
        success_rate: float | None,
        overwrite: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        request_key = self._build_generation_request_key(
            lesson_id=lesson_id,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
            allow_llm=allow_llm,
            mastery=mastery,
            success_rate=success_rate,
            overwrite=overwrite,
            metadata=metadata,
        )
        request_state, is_owner = self._acquire_inflight_generation_request(request_key)
        if not is_owner:
            logger.info(
                "lesson_question_generation_service_join_inflight | lesson_id=%s | key=%s",
                lesson_id,
                request_key[:12],
            )
            request_state["event"].wait()
            error = request_state.get("error")
            if error is not None:
                raise error
            return deepcopy(request_state["result"])
        try:
            result = self._generate_questions_for_lesson_impl(
                lesson_id=lesson_id,
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
                allow_llm=allow_llm,
                mastery=mastery,
                success_rate=success_rate,
                overwrite=overwrite,
                metadata=metadata,
            )
            request_state["result"] = deepcopy(result)
            return result
        except Exception as exc:
            request_state["error"] = exc
            raise
        finally:
            request_state["event"].set()
            with self._inflight_generation_lock:
                self._inflight_generation_requests.pop(request_key, None)

    def _generate_questions_for_lesson_impl(
        self,
        *,
        lesson_id: str,
        target_count: int | None,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        allow_llm: bool,
        mastery: float | None,
        success_rate: float | None,
        overwrite: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        cache_stats_before = self._snapshot_claim_cache_stats()
        source_stats = {
            "template": 0,
            "llm": 0,
            "local_fallback": 0,
            "existing_reuse": 0,
        }
        question_types = self._normalize_requested_question_types(question_types)
        filtered_count = 0
        question_set_kind = self._resolve_question_set_kind(metadata)
        effective_difficulty = self._resolve_adaptive_difficulty(
            requested_difficulty=difficulty,
            mastery=mastery,
            success_rate=success_rate,
            metadata=metadata,
        )
        context = self.lesson_structure_service.get_lesson_context(lesson_id)
        recommendation = self._ensure_generation_recommendation(
            lesson_id=lesson_id,
            context=context,
            metadata=metadata,
        )
        raw_target_concepts = self._extract_target_concepts(metadata)
        if raw_target_concepts and not self._recommendation_covers_target_concepts(
            recommendation=recommendation,
            target_concepts=raw_target_concepts,
        ):
            targeted_refresh = self._refresh_recommendation(
                lesson_id=lesson_id,
                metadata={
                    **metadata,
                    "trigger": "target_concept_refresh",
                    "required_concepts": list(raw_target_concepts),
                },
            )
            if targeted_refresh:
                recommendation = targeted_refresh
        existing_questions = self.question_repository.list_by_lesson(
            lesson_id,
            question_set_kind=question_set_kind,
        )
        existing_count = len(existing_questions)
        excluded_signatures = self._collect_excluded_question_signatures(
            existing_questions=existing_questions,
            generation_metadata=metadata,
        )

        try:
            recommendation, chunk_ids, chunks = self._load_generation_scope(
                lesson_id=lesson_id,
                context=context,
                recommendation=recommendation,
            )
        except ValueError:
            recommendation = self._refresh_recommendation(
                lesson_id=lesson_id,
                metadata={
                    **metadata,
                    "trigger": "question_generation_scope_recovery",
                },
            )
            try:
                recommendation, chunk_ids, chunks = self._load_generation_scope(
                    lesson_id=lesson_id,
                    context=context,
                    recommendation=recommendation,
                )
            except ValueError:
                recommendation, chunk_ids, chunks = (
                    self._build_local_context_generation_scope(
                        lesson_id=lesson_id,
                        context=context,
                    )
                )
                metadata["degraded_mode"] = True
                metadata["degraded_reason"] = "no_recommended_chunks"
                allow_llm = False
        chunks = self._enrich_chunks_with_recommendation_metadata(
            chunks=chunks,
            recommendation=recommendation,
        )
        assessment_plan = self._build_lesson_assessment_plan(
            context=context,
            chunks=chunks,
            mastery=mastery,
            requested_target_count=target_count,
        )
        normalized_target_payload = self._normalize_generation_target_concepts(
            raw_target_concepts=raw_target_concepts,
            context=context,
            chunks=chunks,
        )
        valid_target_concepts = list(
            normalized_target_payload.get("valid_target_concepts", [])
        )
        rejected_target_concepts = list(
            normalized_target_payload.get("rejected_target_concepts", [])
        )
        llm_debug_status = self.llm_client.get_debug_status()
        llm_status_code = self._resolve_llm_status_code(
            allow_llm=allow_llm,
            llm_debug_status=llm_debug_status,
        )
        scope_degraded = str(metadata.get("degraded_reason") or "") == (
            "no_recommended_chunks"
        )
        degraded_mode = (llm_status_code in DEGRADED_LOCAL_STATUSES) or scope_degraded
        usable_chunk_count = self._estimate_usable_chunk_count(chunks)
        grounded_content_volume = self._estimate_grounded_content_volume(chunks)
        declared_lesson_size = assessment_plan.lesson_size
        runtime_effective_lesson_size = self.compute_runtime_effective_lesson_size(
            declared_lesson_size=declared_lesson_size,
            usable_chunk_count=usable_chunk_count,
            grounded_content_volume=grounded_content_volume,
        )
        original_target_count = max(
            1,
            int(
                target_count
                if target_count is not None
                else assessment_plan.target_count_auto
            ),
        )
        bloom_levels = self._resolve_bloom_levels_for_difficulty(
            difficulty=effective_difficulty,
            bloom_levels=bloom_levels,
            target_count=original_target_count,
        )
        runtime_target_count = max(
            1,
            int(
                target_count
                if target_count is not None
                else lesson_assessment_sizing_service.calculate_target_question_count(
                    runtime_effective_lesson_size
                )
            ),
        )
        degraded_target_count = runtime_target_count
        degraded_reason = None
        if degraded_mode:
            degraded_target_count = self.recalculate_target_count_for_degraded_mode(
                lesson_size=runtime_effective_lesson_size,
                original_target_count=original_target_count,
                usable_chunk_count=usable_chunk_count,
                mappable_concept_count=len(valid_target_concepts),
                llm_available=False,
            )
            degraded_reason = (
                "no_recommended_chunks" if scope_degraded else llm_status_code
            )
        target_count = degraded_target_count if degraded_mode else runtime_target_count
        assessment_plan = replace(
            assessment_plan,
            lesson_size=runtime_effective_lesson_size,
            target_count_auto=runtime_target_count,
            difficulty_distribution=lesson_assessment_sizing_service.compute_difficulty_distribution(
                target_count=target_count,
                mastery=mastery,
            ),
            bloom_distribution=self._build_bloom_distribution(
                target_count=target_count,
                lesson_size=runtime_effective_lesson_size,
                bloom_levels=bloom_levels,
            ),
        )
        metadata = self._decorate_generation_metadata(
            metadata=metadata,
            assessment_plan=assessment_plan,
            target_count=target_count,
        )
        metadata.update(
            {
                "question_set_kind": question_set_kind,
                "declared_lesson_size": declared_lesson_size,
                "runtime_effective_lesson_size": runtime_effective_lesson_size,
                "original_target_count": original_target_count,
                "effective_target_count": target_count,
                "degraded_target_count": degraded_target_count if degraded_mode else None,
                "degraded_mode": degraded_mode,
                "degraded_reason": degraded_reason,
                "llm_status": llm_status_code,
                "usable_chunk_count": usable_chunk_count,
                "grounded_content_volume": grounded_content_volume,
                "raw_target_concepts": list(raw_target_concepts),
                "target_concepts": list(valid_target_concepts),
                "valid_target_concepts": list(valid_target_concepts),
                "rejected_target_concepts": list(rejected_target_concepts),
                "concept_mapping_debug": list(
                    normalized_target_payload.get("concept_mapping_debug", [])
                ),
            }
        )

        if not overwrite and existing_questions:
            existing_coverage = self._estimate_existing_concept_coverage(
                questions=existing_questions,
                valid_target_concepts=valid_target_concepts,
            )
            existing_mix = self._summarize_existing_question_mix(existing_questions)
            source_stats["existing_reuse"] = len(existing_questions)
            return {
                "lesson_id": lesson_id,
                "status": "ok",
                "generated_count": 0,
                "saved_count": len(existing_questions),
                "question_ids": [str(item.get("_id")) for item in existing_questions],
                "chunks_used": chunk_ids,
                "insufficient_data": False,
                "reused_existing": True,
                "existing_count": existing_count,
                "sources": source_stats,
                "fallback_used": bool(
                    any(
                        str(
                            (item.get("metadata") or {}).get("generation_source") or ""
                        ).strip()
                        in {"local_fallback", "local_fill"}
                        for item in existing_questions
                    )
                ),
                "cache_stats": self._claim_cache_stats_since(cache_stats_before),
                "filtered_count": 0,
                "lesson_size": assessment_plan.lesson_size,
                "declared_lesson_size": declared_lesson_size,
                "runtime_effective_lesson_size": runtime_effective_lesson_size,
                "target_count": target_count,
                "target_count_auto": assessment_plan.target_count_auto,
                "original_target_count": original_target_count,
                "effective_target_count": target_count,
                "degraded_target_count": degraded_target_count if degraded_mode else None,
                "degraded_mode": degraded_mode,
                "degraded_reason": degraded_reason,
                "llm_status": llm_status_code,
                "difficulty_mix": existing_mix.get(
                    "difficulty_mix", assessment_plan.difficulty_distribution
                ),
                "bloom_mix": existing_mix.get(
                    "bloom_mix", assessment_plan.bloom_distribution
                ),
                "concept_coverage_rate": existing_coverage.get("coverage_rate"),
                "valid_target_concepts": list(valid_target_concepts),
                "rejected_target_concepts": list(rejected_target_concepts),
                "concept_coverage_status": existing_coverage.get(
                    "status", "reused_existing"
                ),
                "next_action": {},
                "message": (
                    "Giữ lại bộ câu hỏi hiện có của lesson vì yêu cầu không cho phép ghi đè."
                ),
            }
        allow_llm = allow_llm and not degraded_mode

        if (
            PREGEN_CHUNK_EXPANSION_ENABLED
            and not degraded_mode
            and target_count >= QUESTION_GENERATION_PREGEN_EXPAND_MIN_TARGET_COUNT
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
                    chunks = self._enrich_chunks_with_recommendation_metadata(
                        chunks=expanded_chunks,
                        recommendation=expanded_recommendation,
                    )
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
            "target_concepts": list(valid_target_concepts),
            "raw_target_concepts": list(raw_target_concepts),
        }
        chunk_text_by_id = {
            str(chunk["_id"]): str(chunk.get("content") or "") for chunk in chunks
        }
        seeded_questions: List[ValidatedLessonQuestion] = []
        additional_llm_questions: List[ValidatedLessonQuestion] = []
        remaining_target = target_count
        if allow_llm:
            validation = self._run_generation(
                context=context,
                recommendation=recommendation,
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
                lesson_summary=str(context["lesson"].get("summary") or ""),
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
                    lesson_summary=str(context["lesson"].get("summary") or ""),
                    chunks=chunks,
                    target_count=remaining_target,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                    target_concepts=context.get("target_concepts") or [],
                    lesson_concepts=assessment_plan.concepts if assessment_plan else [],
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

        should_retry_refresh = (
            not degraded_mode
            and len(chunk_ids) < PREGEN_MIN_RECOMMENDED_CHUNKS
        )
        if validation.status == "insufficient_context" and should_retry_refresh:
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
                chunks = self._enrich_chunks_with_recommendation_metadata(
                    chunks=chunks,
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
                        recommendation=recommendation,
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
                        lesson_summary=str(context["lesson"].get("summary") or ""),
                        chunks=chunks,
                        target_count=remaining_target,
                        question_types=question_types,
                        difficulty=effective_difficulty,
                        bloom_levels=bloom_levels,
                        retry_attempts=3,
                        target_concepts=context.get("target_concepts") or [],
                        lesson_concepts=assessment_plan.concepts if assessment_plan else [],
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
                cache_stats=self._claim_cache_stats_since(cache_stats_before),
            )
            if allow_llm:
                validation = self._build_validation_from_fallback(
                    questions=[],
                    message=self._build_llm_fallback_message(
                        "Không thể nhận phản hồi hợp lệ từ dịch vụ tạo câu hỏi."
                    ),
                )
            else:
                return self._build_existing_or_insufficient_response(
                lesson_id=lesson_id,
                chunk_ids=chunk_ids,
                default_message="Không thể nhận phản hồi hợp lệ từ dịch vụ tạo câu hỏi.",
                source_stats=source_stats,
                filtered_count=filtered_count,
                cache_stats=self._claim_cache_stats_since(cache_stats_before),
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
                cache_stats=self._claim_cache_stats_since(cache_stats_before),
            )
            if allow_llm:
                validation = self._build_validation_from_fallback(
                    questions=[],
                    message=self._build_llm_fallback_message(validation.message),
                )
            else:
                cache_stats = self._claim_cache_stats_since(cache_stats_before)
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
                    "fallback_used": bool(source_stats.get("local_fallback", 0)),
                    "cache_stats": cache_stats,
                    "filtered_count": filtered_count,
                    "message": validation.message,
                }
        if validation.status != "ok":
            llm_status_code = self._resolve_llm_status_code(
                allow_llm=True,
                llm_debug_status=self.llm_client.get_debug_status(),
                validation=validation,
            )
            if llm_status_code in DEGRADED_LOCAL_STATUSES and not degraded_mode:
                degraded_mode = True
                degraded_reason = llm_status_code
                target_count = self.recalculate_target_count_for_degraded_mode(
                    lesson_size=runtime_effective_lesson_size,
                    original_target_count=original_target_count,
                    usable_chunk_count=usable_chunk_count,
                    mappable_concept_count=len(valid_target_concepts),
                    llm_available=False,
                )
                metadata["effective_target_count"] = target_count
                metadata["degraded_mode"] = True
                metadata["degraded_reason"] = degraded_reason
                metadata["degraded_target_count"] = target_count
                metadata["llm_status"] = llm_status_code
                assessment_plan = replace(
                    assessment_plan,
                    target_count_auto=target_count,
                    difficulty_distribution=lesson_assessment_sizing_service.compute_difficulty_distribution(
                        target_count=target_count,
                        mastery=mastery,
                    ),
                    bloom_distribution=self._build_bloom_distribution(
                        target_count=target_count,
                        lesson_size=runtime_effective_lesson_size,
                        bloom_levels=bloom_levels,
                    ),
                )
            refreshed = None
            if should_retry_refresh:
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
                lesson_summary=str(context["lesson"].get("summary") or ""),
                chunks=chunks,
                target_count=target_count,
                question_types=question_types,
                difficulty=effective_difficulty,
                bloom_levels=bloom_levels,
                retry_attempts=3,
                target_concepts=context.get("target_concepts") or [],
                lesson_concepts=assessment_plan.concepts if assessment_plan else [],
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
                    default_message="Hệ thống tạm thời chưa tạo được câu hỏi tự động từ nội dung bài học hiện tại.",
                    source_stats=source_stats,
                    filtered_count=filtered_count,
                    cache_stats=self._claim_cache_stats_since(cache_stats_before),
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
            if (
                remaining_target > 0
                and PREFER_LLM_FILL_BEFORE_TEMPLATE_ENABLED
                and llm_status_code == "available"
            ):
                additional_llm_questions = self._collect_additional_llm_questions(
                    context=context,
                    recommendation=recommendation,
                    chunks=chunks,
                    chunk_ids=chunk_ids,
                    existing_questions=list(validation.questions),
                    target_count=target_count,
                    question_types=question_types,
                    difficulty=effective_difficulty,
                    bloom_levels=bloom_levels,
                )
                if additional_llm_questions:
                    validation = self._build_validation_from_fallback(
                        questions=[
                            *list(validation.questions),
                            *additional_llm_questions,
                        ],
                        message=validation.message,
                        status="ok",
                    )
                    remaining_target = max(0, target_count - len(validation.questions))
            if remaining_target > 0:
                template_validation = self._build_template_validation(
                    lesson_title=str(context["lesson"].get("title") or ""),
                    lesson_summary=str(context["lesson"].get("summary") or ""),
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
            generation_metadata=metadata,
            excluded_signatures=excluded_signatures,
            assessment_plan=assessment_plan,
            degraded_mode=degraded_mode,
        )
        filtered_count += int(metadata.pop("semantic_filtered_count", 0) or 0)
        filtered_count += int(metadata.pop("verification_filtered_count", 0) or 0)


        if (
            LOW_COUNT_REGEN_RETRY_ENABLED
            and allow_llm
            and llm_status_code == "available"
            and not degraded_mode
            and usable_chunk_count >= 4
            and target_count >= 4
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
                recommendation=recommendation,
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
                    generation_metadata=metadata,
                    excluded_signatures=excluded_signatures,
                    assessment_plan=assessment_plan,
                    degraded_mode=degraded_mode,
                )
                retry_semantic_filtered = int(metadata.pop("semantic_filtered_count", 0) or 0)
                retry_verification_filtered = int(
                    metadata.pop("verification_filtered_count", 0) or 0
                )
                if len(retried_questions) > len(finalized_questions):
                    finalized_questions = retried_questions
                    finalized_message = retried_message
                    filtered_count += retry_semantic_filtered + retry_verification_filtered
                    logger.info(
                        "lesson_question_generation_low_count_retry_improved | lesson_id=%s | generated=%s | target=%s",
                        lesson_id,
                        len(finalized_questions),
                        target_count,
                    )
                else:
                    filtered_count += retry_semantic_filtered + retry_verification_filtered

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
                cache_stats=self._claim_cache_stats_since(cache_stats_before),
            )
            return self._build_existing_or_insufficient_response(
                lesson_id=lesson_id,
                chunk_ids=chunk_ids,
                default_message="Không đủ dữ liệu phù hợp để tạo bộ câu hỏi chất lượng cho bài học này.",
                source_stats=source_stats,
                filtered_count=filtered_count,
                cache_stats=self._claim_cache_stats_since(cache_stats_before),
            )

        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        coverage_report = self.compute_concept_coverage_rate(
            finalized_questions,
            valid_target_concepts=valid_target_concepts,
            chunk_map=chunk_map,
        )
        metadata["concept_coverage_rate"] = coverage_report.get("coverage_rate")
        metadata["concept_coverage_status"] = coverage_report.get("status")
        metadata["concept_coverage_missing"] = list(
            coverage_report.get("missing_concepts", [])
        )
        metadata["concept_coverage_pass"] = bool(
            coverage_report.get("is_valid", False)
        )
        metadata["final_generation_status"] = self.resolve_generation_status(
            saved_count=len(finalized_questions),
            effective_target_count=target_count,
            concept_coverage_rate=coverage_report.get("coverage_rate"),
            llm_available=bool(llm_debug_status.get("client_available"))
            and not bool(llm_debug_status.get("cooldown_active")),
            degraded_mode=degraded_mode,
        )
        next_action = self._build_generation_next_action(
            llm_status=llm_status_code,
            llm_debug_status=llm_debug_status,
            concept_coverage_status=str(coverage_report.get("status") or ""),
            degraded_mode=degraded_mode,
        )
        finalized_message = self.build_generation_message(
            llm_status=llm_status_code,
            degraded_mode=degraded_mode,
            original_target_count=original_target_count,
            effective_target_count=target_count,
            usable_chunk_count=usable_chunk_count,
            saved_count=len(finalized_questions),
            concept_coverage_rate=coverage_report.get("coverage_rate"),
            concept_coverage_status=str(coverage_report.get("status") or ""),
        )

        # Always replace the current lesson question set when a new valid set is generated.
        # This keeps one authoritative set per lesson and avoids duplicate buildup.
        if overwrite or existing_count > 0:
            self.question_semantic_memory_repository.delete_by_lesson(lesson_id)
            self.question_repository.delete_by_lesson(
                lesson_id,
                question_set_kind=question_set_kind,
            )

        resource_ids = [str(item) for item in recommendation.get("resource_ids", [])]
        documents = []
        for question in finalized_questions:
            question_resource_ids = sorted(
                {
                    str(chunk_map[chunk_id].get("resource_id"))
                    for chunk_id in question.chunk_ids
                    if chunk_id in chunk_map and chunk_map[chunk_id].get("resource_id")
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
                or "paraphrase_question"
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
                        chunk_map[chunk_id].get("resource_id")
                        for chunk_id in question.chunk_ids
                        if chunk_id in chunk_map and chunk_map[chunk_id].get("resource_id")
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
                            (
                                "local_fallback"
                                if str(
                                    question.metadata.get("generation_source")
                                    or question.metadata.get("generation_mode")
                                    or ""
                                ).strip()
                                == "local_fill"
                                else (
                                    question.metadata.get("generation_source")
                                    or question.metadata.get("generation_mode")
                                )
                            )
                            or "llm"
                        ),
                        "source": str(
                            (
                                "local_fallback"
                                if str(
                                    question.metadata.get("generation_source")
                                    or question.metadata.get("generation_mode")
                                    or ""
                                ).strip()
                                == "local_fill"
                                else (
                                    question.metadata.get("generation_source")
                                    or question.metadata.get("generation_mode")
                                )
                            )
                            or "llm"
                        ),
                        "lesson_id": lesson_id,
                        "question_set_kind": question_set_kind,
                        "chunk_id": (
                            str(question.chunk_ids[0]) if question.chunk_ids else None
                        ),
                        "resource_id": (
                            question_resource_ids[0] if question_resource_ids else None
                        ),
                        "target_concepts": list(
                            question.metadata.get("target_concepts")
                            or metadata.get("target_concepts")
                            or []
                        ),
                        "bloom_level": question.bloom_level,
                        "difficulty": question.difficulty,
                        "quality_score": float(
                            question.metadata.get("quality_score") or 0.0
                        ),
                        "generation_reason": str(
                            metadata.get("generation_reason")
                            or question.metadata.get("generation_reason")
                            or "lesson_question_generation"
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
        self._persist_question_semantic_memory(
            question_ids=inserted_ids,
            questions=finalized_questions,
            context=context,
        )
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
            status=str(metadata.get("final_generation_status") or "ok"),
            generation_mode=generation_mode,
            question_count=len(inserted_ids),
            chunk_count=len(chunk_ids),
            covered_chunk_count=covered_chunk_count,
            llm_error=self.llm_client.get_last_error(),
            message=finalized_message,
            cache_stats=self._claim_cache_stats_since(cache_stats_before),
            runtime_details={
                "declared_lesson_size": declared_lesson_size,
                "runtime_effective_lesson_size": runtime_effective_lesson_size,
                "original_target_count": original_target_count,
                "degraded_target_count": degraded_target_count if degraded_mode else None,
                "usable_chunk_count": usable_chunk_count,
                "valid_target_concepts": list(valid_target_concepts),
                "rejected_target_concepts": list(rejected_target_concepts),
                "concept_coverage_status": metadata.get("concept_coverage_status"),
                "final_generation_status": metadata.get("final_generation_status"),
                "verification_filtered_count": metadata.get("verification_filtered_count"),
                "verification_blockers": (
                    (metadata.get("verification_diagnostics") or {}).get("blocker_counts")
                ),
                "reasoning_patterns": (
                    (metadata.get("final_question_diagnostics") or {}).get("reasoning_pattern_counts")
                ),
            },
        )
        return {
            "lesson_id": lesson_id,
            "status": str(metadata.get("final_generation_status") or "ok"),
            "generated_count": len(inserted_ids),
            "saved_count": len(inserted_ids),
            "question_ids": inserted_ids,
            "chunks_used": chunk_ids,
            "insufficient_data": False,
            "reused_existing": False,
            "existing_count": existing_count,
            "sources": source_stats,
            "fallback_used": bool(source_stats.get("local_fallback", 0)),
            "cache_stats": self._claim_cache_stats_since(cache_stats_before),
            "filtered_count": filtered_count,
            "lesson_size": assessment_plan.lesson_size,
            "declared_lesson_size": declared_lesson_size,
            "runtime_effective_lesson_size": runtime_effective_lesson_size,
            "target_count": target_count,
            "target_count_auto": assessment_plan.target_count_auto,
            "original_target_count": original_target_count,
            "effective_target_count": target_count,
            "degraded_target_count": degraded_target_count if degraded_mode else None,
            "degraded_mode": degraded_mode,
            "degraded_reason": degraded_reason,
            "llm_status": llm_status_code,
            "difficulty_mix": assessment_plan.difficulty_distribution,
            "bloom_mix": assessment_plan.bloom_distribution,
            "concept_coverage_rate": metadata.get("concept_coverage_rate"),
            "valid_target_concepts": list(valid_target_concepts),
            "rejected_target_concepts": list(rejected_target_concepts),
            "concept_coverage_status": metadata.get("concept_coverage_status"),
            "verification_diagnostics": metadata.get("verification_diagnostics"),
            "final_question_diagnostics": metadata.get("final_question_diagnostics"),
            "next_action": next_action,
            "message": finalized_message,
        }

    def inspect_generation_debug(
        self,
        *,
        lesson_id: str,
        target_count: int | None,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        allow_llm: bool,
        mastery: float | None,
        success_rate: float | None,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        question_types = self._normalize_requested_question_types(question_types)
        effective_difficulty = self._resolve_adaptive_difficulty(
            requested_difficulty=difficulty,
            mastery=mastery,
            success_rate=success_rate,
            metadata=metadata,
        )
        context = self.lesson_structure_service.get_lesson_context(lesson_id)
        target_concepts = self._extract_target_concepts(metadata)
        recommendation = self._ensure_generation_recommendation(
            lesson_id=lesson_id,
            context=context,
            metadata=metadata,
        )
        existing_count = len(self.question_repository.list_by_lesson(lesson_id))
        llm_status = self.llm_client.get_debug_status()
        generation_strategy = (
            metadata.get("generation_strategy", {})
            if isinstance(metadata.get("generation_strategy"), dict)
            else {}
        )

        blockers: List[str] = []
        warnings: List[str] = []
        chunks: List[Dict[str, Any]] = []
        chunk_ids: List[str] = []
        loaded_chunk_ids: List[str] = []
        missing_chunk_ids: List[str] = []
        scope_error: str | None = None
        scope_ready = False

        if not allow_llm:
            blockers.append("llm_disabled_by_request")
        if generation_strategy.get("prefer_template") is True:
            warnings.append("prefer_template_enabled")
        if generation_strategy.get("allow_llm") is False:
            warnings.append("generation_strategy_disables_llm")

        recommendation_covers_targets = self._recommendation_covers_target_concepts(
            recommendation=recommendation,
            target_concepts=target_concepts,
        )
        if target_concepts and not recommendation_covers_targets:
            warnings.append("recommendation_does_not_cover_target_concepts")

        if allow_llm and not bool(llm_status.get("client_available")):
            blockers.append("llm_client_unavailable")
        if allow_llm and bool(llm_status.get("cooldown_active")):
            blockers.append("llm_cooldown_active")

        if recommendation:
            try:
                _, chunk_ids, chunks = self._load_generation_scope(
                    lesson_id=lesson_id,
                    context=context,
                    recommendation=recommendation,
                )
                loaded_chunk_ids = [str(chunk.get("_id") or "") for chunk in chunks]
                missing_chunk_ids = [
                    chunk_id for chunk_id in chunk_ids if chunk_id not in set(loaded_chunk_ids)
                ]
                scope_ready = bool(loaded_chunk_ids)
                if not scope_ready:
                    scope_error = "Recommended chunks could not be loaded."
                    blockers.append("generation_scope_unavailable")
                elif missing_chunk_ids:
                    warnings.append("recommendation_contains_missing_chunks")
            except ValueError as exc:
                scope_error = str(exc)
                blockers.append("generation_scope_unavailable")
        else:
            scope_error = "Lesson has no recommended chunks after refresh attempt."
            blockers.append("missing_recommendation")

        recommendation_metadata = recommendation.get("metadata", {}) if recommendation else {}
        assessment_plan = self._build_lesson_assessment_plan(
            context=context,
            chunks=chunks,
            mastery=mastery,
            requested_target_count=target_count,
        )
        resolved_target_count = max(
            1,
            int(
                target_count
                if target_count is not None
                else assessment_plan.target_count_auto
            ),
        )
        recommendation_source = str(
            recommendation_metadata.get("source")
            or ("stored_recommendation" if recommendation and recommendation.get("_id") else "")
        ).strip() or None
        nlp_status = self.question_fallback_service.question_nlp_service.get_backend_status()
        chunk_debug: List[Dict[str, Any]] = []
        if chunks:
            chunk_profiles = self.question_fallback_service._build_chunk_profiles(
                chunks=chunks,
                target_concepts=target_concepts,
            )
            for chunk in chunks:
                chunk_id = str(chunk.get("_id") or "").strip()
                profile = chunk_profiles.get(chunk_id, {})
                chunk_debug.append(
                    {
                        "chunk_id": chunk_id,
                        "instruction_role": str(
                            profile.get("instruction_role")
                            or chunk.get("instruction_role")
                            or "explanation"
                        ),
                        "covered_concepts": list(profile.get("covered_concepts") or []),
                        "target_match": bool(profile.get("target_match")),
                        "target_semantic_score": round(
                            float(profile.get("target_semantic_score", 0.0) or 0.0),
                            4,
                        ),
                        "target_lexical_score": round(
                            float(profile.get("target_lexical_score", 0.0) or 0.0),
                            4,
                        ),
                        "keyword_overlap_terms": list(
                            profile.get("keyword_overlap_terms") or []
                        ),
                        "questionability_score": round(
                            float(profile.get("questionability_score", 0.0) or 0.0),
                            4,
                        ),
                        "priority_score": round(
                            float(profile.get("priority_score", 0.0) or 0.0),
                            4,
                        ),
                        "llm_priority_score": round(
                            float(
                                self.question_llm_service._chunk_generation_priority(
                                    chunk,
                                    bloom_levels=bloom_levels,
                                )
                                or 0.0
                            ),
                            4,
                        ),
                        "claim_count": int(profile.get("claim_count", 0) or 0),
                        "has_code": bool(profile.get("has_code")),
                        "has_example": bool(profile.get("has_example")),
                        "estimated_read_time": round(
                            float(profile.get("estimated_read_time", 0.0) or 0.0),
                            2,
                        ),
                    }
                )
            chunk_debug.sort(
                key=lambda item: float(item.get("priority_score", 0.0) or 0.0),
                reverse=True,
            )

        predicted_generation_path = "llm_attempt_expected"
        if not scope_ready:
            predicted_generation_path = "blocked_before_generation"
        elif not allow_llm:
            predicted_generation_path = "template_then_local_fallback_only"
        elif (
            not bool(llm_status.get("client_available"))
            or bool(llm_status.get("cooldown_active"))
        ):
            predicted_generation_path = "llm_requested_but_local_fallback_expected"

        message = "LLM preflight looks ready."
        if not scope_ready:
            message = scope_error or "Question generation scope is not ready."
        elif not allow_llm:
            message = (
                "LLM is disabled by request or adaptive config; generation will use "
                "template/local fallback."
            )
        elif not bool(llm_status.get("client_available")):
            message = str(
                llm_status.get("init_error")
                or llm_status.get("last_error")
                or "Lesson question LLM client is unavailable."
            )
        elif bool(llm_status.get("cooldown_active")):
            message = (
                "Lesson question LLM is in cooldown after quota exhaustion; "
                "generation will fall back locally until cooldown expires."
            )
        elif target_concepts and not recommendation_covers_targets:
            message = (
                "LLM can run, but current recommended chunks do not cover the requested "
                "target concepts well."
            )

        return {
            "lesson_id": lesson_id,
            "target_count": resolved_target_count,
            "question_types": list(question_types),
            "requested_difficulty": difficulty,
            "effective_difficulty": effective_difficulty,
            "bloom_levels": list(bloom_levels),
            "llm_requested": allow_llm,
            "predicted_generation_path": predicted_generation_path,
            "target_concepts": list(target_concepts),
            "existing_count": existing_count,
            "recommendation_available": bool(recommendation),
            "recommendation_source": recommendation_source,
            "recommendation_selection_strategy": (
                str(recommendation.get("selection_strategy") or "").strip()
                if recommendation
                else None
            ),
            "recommendation_chunk_count": len(recommendation.get("chunk_ids", []))
            if recommendation
            else 0,
            "recommendation_resource_count": len(recommendation.get("resource_ids", []))
            if recommendation
            else 0,
            "recommendation_covers_target_concepts": recommendation_covers_targets,
            "scope_ready": scope_ready,
            "scope_error": scope_error,
            "chunk_ids": chunk_ids,
            "loaded_chunk_ids": loaded_chunk_ids,
            "missing_chunk_ids": missing_chunk_ids,
            "nlp_status": nlp_status,
            "chunk_debug": chunk_debug,
            "llm_status": llm_status,
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": list(dict.fromkeys(warnings)),
            "message": message,
        }

    def get_questions_for_lesson(
        self,
        lesson_id: str,
        question_set_kind: str | None = None,
    ) -> Dict[str, Any]:
        requested_kind = str(question_set_kind or "").strip().lower() or None
        if requested_kind:
            questions = self.question_repository.list_by_lesson(
                lesson_id,
                question_set_kind=requested_kind,
            )
        else:
            all_questions = self.question_repository.list_by_lesson(lesson_id)
            latest_kind = (
                self._extract_question_set_kind_from_document(all_questions[0])
                if all_questions
                else STANDARD_QUESTION_SET_KIND
            )
            questions = [
                item
                for item in all_questions
                if self._extract_question_set_kind_from_document(item) == latest_kind
            ]
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

    def _resolve_question_set_kind(self, metadata: Dict[str, Any] | None) -> str:
        payload = metadata if isinstance(metadata, dict) else {}
        explicit = str(payload.get("question_set_kind") or "").strip().lower()
        if explicit:
            return explicit
        generation_reason = str(payload.get("generation_reason") or "").strip().lower()
        if bool(payload.get("adaptive_quiz")) or bool(payload.get("adaptive_loop")):
            return ADAPTIVE_QUESTION_SET_KIND
        if generation_reason in ADAPTIVE_GENERATION_REASONS:
            return ADAPTIVE_QUESTION_SET_KIND
        return STANDARD_QUESTION_SET_KIND

    def _extract_question_set_kind_from_document(
        self,
        question: Dict[str, Any] | None,
    ) -> str:
        payload = question if isinstance(question, dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return self._resolve_question_set_kind(metadata)

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
        generation_metadata: Dict[str, Any],
        excluded_signatures: set[str] | None = None,
        assessment_plan: LessonAssessmentSizingResult | None = None,
        degraded_mode: bool = False,
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
        allowed_question_types = set(
            self._normalize_requested_question_types(question_types)
        )
        candidate_pool: List[ValidatedLessonQuestion] = []
        seen_signatures: set[str] = set(excluded_signatures or set())
        for candidate in ordered_questions:
            if candidate.question_type not in allowed_question_types:
                continue
            signature = self._question_signature(candidate)
            if not signature or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            candidate_pool.append(
                self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    generation_metadata=generation_metadata,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
            )
            if len(candidate_pool) >= max(target_count * 2, target_count + 4):
                break

        if len(candidate_pool) < target_count:
            fallback_questions = self._build_fallback_questions(
                context=context,
                chunks=chunks,
                target_count=max(target_count + 4, target_count * 2),
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            for candidate in fallback_questions:
                if candidate.question_type not in allowed_question_types:
                    continue
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                enriched_candidate = self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    generation_metadata=generation_metadata,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
                candidate_pool.append(enriched_candidate)

        pre_strict_filter_pool = list(candidate_pool)
        if LOW_COUNT_FORCE_FILL_ENABLED and len(candidate_pool) < target_count:
            remaining = target_count - len(candidate_pool)
            relaxed_fallback_questions = self._build_fallback_questions(
                context=context,
                chunks=chunks,
                target_count=max(remaining * 3, target_count),
                question_types=["multiple_choice"],
                difficulty=difficulty,
                bloom_levels=bloom_levels,
                relaxed_mode=True,
            )
            for candidate in relaxed_fallback_questions:
                if candidate.question_type not in allowed_question_types:
                    continue
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                enriched_candidate = self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    generation_metadata=generation_metadata,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
                candidate_pool.append(enriched_candidate)

        if len(candidate_pool) < target_count:
            medium_fill_questions = self._build_reinforcement_questions(
                context=context,
                chunks=chunks,
                target_count=target_count - len(candidate_pool),
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            for candidate in medium_fill_questions:
                if candidate.question_type not in allowed_question_types:
                    continue
                signature = self._question_signature(candidate)
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                enriched_candidate = self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    generation_metadata=generation_metadata,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
                candidate_pool.append(enriched_candidate)

        if not candidate_pool:
            return [], base_message or "Không thể tạo câu hỏi hợp lệ từ lesson này."

        required_target_concepts = self._extract_target_concepts(generation_metadata)
        if required_target_concepts:
            matched_pool = [
                item
                for item in candidate_pool
                if bool((item.metadata or {}).get("target_concept_match"))
            ]
            if matched_pool:
                unmatched_pool = [
                    item
                    for item in candidate_pool
                    if not bool((item.metadata or {}).get("target_concept_match"))
                ]
                candidate_pool = matched_pool + unmatched_pool

        candidate_pool, semantic_filtered_count = self._semantic_deduplicate_candidates(
            context=context,
            questions=candidate_pool,
            target_concepts=required_target_concepts,
        )
        generation_metadata["semantic_filtered_count"] = int(
            generation_metadata.get("semantic_filtered_count", 0) or 0
        ) + int(semantic_filtered_count or 0)
        pre_verification_pool = list(candidate_pool)
        candidate_pool, verification_filtered_count, verification_diagnostics = self._verify_candidate_questions(
            questions=candidate_pool,
            target_concepts=required_target_concepts,
            requested_bloom_levels=bloom_levels,
            chunk_map=chunk_map,
        )
        if not candidate_pool and pre_verification_pool:
            salvaged_pool = self._extend_with_salvageable_local_questions(
                current_questions=[],
                source_questions=pre_verification_pool,
                target_count=target_count,
            )
            if salvaged_pool:
                candidate_pool = [
                    replace(
                        item,
                        metadata={
                            **dict(item.metadata or {}),
                            "verification_salvaged": True,
                            "verification_pass": False,
                            "verification_hard_fail": False,
                        },
                    )
                    for item in salvaged_pool
                ]
                verification_diagnostics = {
                    **verification_diagnostics,
                    "salvaged_count": len(candidate_pool),
                }
        generation_metadata["verification_filtered_count"] = int(
            generation_metadata.get("verification_filtered_count", 0) or 0
        ) + int(verification_filtered_count or 0)
        generation_metadata["verification_diagnostics"] = verification_diagnostics

        coverage_report = self._validate_selected_concept_coverage(
            candidate_pool,
            assessment_plan=assessment_plan,
            required_concepts=required_target_concepts,
        )
        if assessment_plan and not coverage_report.get("is_valid", True):
            missing_candidates = self._build_missing_concept_candidates(
                context=context,
                chunks=chunks,
                missing_concepts=coverage_report.get("missing_concepts", []),
                target_count=max(
                    len(coverage_report.get("missing_concepts", [])),
                    int(
                        assessment_plan.coverage_requirement.get(
                            "required_concept_count", 1
                        )
                        or 1
                    ),
                ),
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
                chunk_map=chunk_map,
                resource_map=resource_map,
                score_map=score_map,
                seen_signatures=seen_signatures,
                generation_metadata=generation_metadata,
            )
            candidate_pool.extend(missing_candidates)

        pre_filter_finalized = list(candidate_pool)
        finalized = self._select_diverse_questions(
            questions=candidate_pool,
            target_count=target_count,
            assessment_plan=assessment_plan,
            required_concepts=required_target_concepts,
        )
        finalized = [
            item for item in finalized if not self._is_low_quality_local_question(item)
        ]
        if len(finalized) < target_count:
            finalized = self._extend_with_salvageable_local_questions(
                current_questions=finalized,
                source_questions=pre_filter_finalized,
                target_count=target_count,
            )
        if degraded_mode and len(finalized) < target_count:
            finalized = self._extend_with_degraded_fill_candidates(
                current_questions=finalized,
                source_questions=pre_strict_filter_pool,
                target_count=target_count,
            )
        finalized = self._apply_quiz_distribution_plan(
            finalized,
            assessment_plan=assessment_plan,
        )
        if not finalized:
            return [], base_message or "Khong the tao cau hoi hop le tu lesson nay."

        coverage_report = self._validate_selected_concept_coverage(
            finalized,
            assessment_plan=assessment_plan,
            required_concepts=required_target_concepts,
        )
        generation_metadata["concept_coverage_rate"] = coverage_report.get(
            "coverage_rate", 0.0
        )
        generation_metadata["concept_coverage_missing"] = list(
            coverage_report.get("missing_concepts", [])
        )
        generation_metadata["concept_coverage_pass"] = bool(
            coverage_report.get("is_valid", False)
        )
        generation_metadata["final_question_diagnostics"] = self._summarize_question_diagnostics(
            finalized
        )

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
        if assessment_plan:
            message = (
                f"{message} Lesson size: {assessment_plan.lesson_size}; "
                f"coverage concept: {coverage_report.get('coverage_rate', 0.0):.0%}."
            )
        minimum_viable_fallback = 1
        if used_local_fallback and len(finalized) < minimum_viable_fallback:
            return [], (
                "Du lieu lesson hien chua du sach de tao bo cau hoi cuc bo dang tin cay. "
                "He thong da bo qua cac cau hoi co dau hieu nhieu. Hay thu lai khi LLM kha dung."
            )
        return finalized, message

    def _summarize_question_diagnostics(
        self,
        questions: Sequence[ValidatedLessonQuestion],
    ) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {
            "count": len(list(questions or [])),
            "avg_quality_score": 0.0,
            "avg_verification_score": 0.0,
            "avg_stem_quality": 0.0,
            "question_type_counts": {},
            "reasoning_pattern_counts": {},
            "blocker_counts": {},
        }
        if not questions:
            return diagnostics

        quality_scores: List[float] = []
        verification_scores: List[float] = []
        stem_scores: List[float] = []
        question_type_counts: Dict[str, int] = {}
        reasoning_pattern_counts: Dict[str, int] = {}
        blocker_counts: Dict[str, int] = {}

        for question in questions:
            metadata = question.metadata or {}
            quality_scores.append(float(metadata.get("quality_score", 0.0) or 0.0))
            verification_scores.append(
                float(metadata.get("verification_score", 0.0) or 0.0)
            )
            stem_scores.append(
                float(
                    ((metadata.get("verification_checks") or {}).get("stem_quality", 0.0))
                    or 0.0
                )
            )
            question_type = str(question.question_type or "").strip().lower()
            if question_type:
                question_type_counts[question_type] = (
                    question_type_counts.get(question_type, 0) + 1
                )
            reasoning_pattern = self._normalize_text(
                str(metadata.get("reasoning_pattern") or "")
            )
            if reasoning_pattern:
                reasoning_pattern_counts[reasoning_pattern] = (
                    reasoning_pattern_counts.get(reasoning_pattern, 0) + 1
                )
            for blocker in metadata.get("verification_blockers") or []:
                blocker_key = self._normalize_text(str(blocker or ""))
                if blocker_key:
                    blocker_counts[blocker_key] = blocker_counts.get(blocker_key, 0) + 1

        diagnostics["avg_quality_score"] = round(
            sum(quality_scores) / max(len(quality_scores), 1), 4
        )
        diagnostics["avg_verification_score"] = round(
            sum(verification_scores) / max(len(verification_scores), 1), 4
        )
        diagnostics["avg_stem_quality"] = round(
            sum(stem_scores) / max(len(stem_scores), 1), 4
        )
        diagnostics["question_type_counts"] = question_type_counts
        diagnostics["reasoning_pattern_counts"] = reasoning_pattern_counts
        diagnostics["blocker_counts"] = blocker_counts
        return diagnostics

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

    def _select_diverse_questions(
        self,
        *,
        questions: Sequence[ValidatedLessonQuestion],
        target_count: int,
        assessment_plan: LessonAssessmentSizingResult | None = None,
        required_concepts: Sequence[str] | None = None,
    ) -> List[ValidatedLessonQuestion]:
        remaining = list(questions)
        if target_count <= 0 or not remaining:
            return []

        selected: List[ValidatedLessonQuestion] = []
        used_chunks: set[str] = set()
        used_focuses: set[str] = set()
        used_types: Dict[str, int] = {}
        used_resources: set[str] = set()
        used_reasoning_patterns: set[str] = set()

        while remaining and len(selected) < target_count:
            best_index = 0
            best_score = -1e9
            for index, question in enumerate(remaining):
                metadata = question.metadata or {}
                score = float(metadata.get("quality_score", 0.0) or 0.0)
                verification_score = float(metadata.get("verification_score", 0.0) or 0.0)
                stem_quality = float(
                    ((metadata.get("verification_checks") or {}).get("stem_quality", 0.0))
                    or 0.0
                )
                blocker_count = len(list(metadata.get("verification_blockers") or []))
                reasoning_pattern = self._normalize_text(
                    str(metadata.get("reasoning_pattern") or "")
                )
                focus_key = self._normalize_text(
                    str(metadata.get("question_focus") or question.correct_answer or "")
                )
                resource_ids = {
                    str(item)
                    for item in metadata.get("source_resource_ids", [])
                    if str(item).strip()
                }
                if not resource_ids and metadata.get("source_resource_id"):
                    resource_ids.add(str(metadata.get("source_resource_id")))

                new_chunk_count = len(
                    {chunk_id for chunk_id in question.chunk_ids if chunk_id not in used_chunks}
                )
                score += min(new_chunk_count, 2) * 0.65
                if bool(metadata.get("target_concept_match")):
                    score += 1.15
                score += verification_score * 1.1
                score += stem_quality * 0.9
                if bool(metadata.get("verification_pass")):
                    score += 0.8
                elif metadata.get("verification_hard_fail"):
                    score -= 1.2
                score -= blocker_count * 0.22
                if focus_key and focus_key not in used_focuses:
                    score += 0.8
                else:
                    score -= 0.25
                if reasoning_pattern:
                    if reasoning_pattern not in used_reasoning_patterns:
                        score += 0.38
                    else:
                        score -= 0.08
                score += 0.35 / (1 + used_types.get(question.question_type, 0))
                if resource_ids and not resource_ids.issubset(used_resources):
                    score += 0.25
                if used_types.get(question.question_type, 0) >= 2:
                    score -= 0.2
                if len(question.chunk_ids) > 1:
                    score += 0.15
                if assessment_plan:
                    current_coverage = self._validate_selected_concept_coverage(
                        selected,
                        assessment_plan=assessment_plan,
                        required_concepts=required_concepts,
                    )
                    missing_concepts = set(
                        current_coverage.get("missing_concepts", [])
                    )
                    question_concepts = set(self._extract_question_concepts(question))
                    score += float(
                        len(missing_concepts.intersection(question_concepts))
                    ) * 1.35
                    matched_targets = (
                        question.metadata.get("matched_target_concepts", [])
                        if isinstance(question.metadata, dict)
                        else []
                    )
                    score += float(len(matched_targets or [])) * 0.45

                    difficulty_counts = self._count_selected_difficulties(selected)
                    difficulty_targets = (
                        assessment_plan.difficulty_distribution.get("counts", {})
                    )
                    difficulty_key = (
                        lesson_assessment_sizing_service.normalize_difficulty_label(
                            question.difficulty
                        )
                    )
                    if difficulty_counts.get(difficulty_key, 0) < difficulty_targets.get(
                        difficulty_key, 0
                    ):
                        score += 0.95

                    bloom_counts = self._count_selected_bloom_levels(selected)
                    bloom_targets = assessment_plan.bloom_distribution.get("counts", {})
                    if bloom_counts.get(question.bloom_level, 0) < bloom_targets.get(
                        question.bloom_level, 0
                    ):
                        score += 1.05
                    if question.bloom_level == "apply" and bloom_targets.get("apply", 0):
                        score += 0.35
                    if (
                        assessment_plan.lesson_size in {"medium", "large"}
                        and question.bloom_level == "analyze"
                    ):
                        score += 0.3
                if score > best_score:
                    best_score = score
                    best_index = index

            chosen = remaining.pop(best_index)
            selected.append(chosen)
            used_chunks.update(str(chunk_id) for chunk_id in chosen.chunk_ids if str(chunk_id).strip())
            focus_key = self._normalize_text(
                str((chosen.metadata or {}).get("question_focus") or chosen.correct_answer or "")
            )
            if focus_key:
                used_focuses.add(focus_key)
            reasoning_pattern = self._normalize_text(
                str((chosen.metadata or {}).get("reasoning_pattern") or "")
            )
            if reasoning_pattern:
                used_reasoning_patterns.add(reasoning_pattern)
            used_types[chosen.question_type] = used_types.get(chosen.question_type, 0) + 1
            resource_ids = {
                str(item)
                for item in (chosen.metadata or {}).get("source_resource_ids", [])
                if str(item).strip()
            }
            if not resource_ids and (chosen.metadata or {}).get("source_resource_id"):
                resource_ids.add(str((chosen.metadata or {}).get("source_resource_id")))
            used_resources.update(resource_ids)

        return selected[:target_count]

    def _build_lesson_assessment_plan(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        mastery: float | None,
        requested_target_count: int | None,
    ) -> LessonAssessmentSizingResult:
        lesson = context.get("lesson") or {}
        lesson_concepts = self._resolve_lesson_concepts(context=context, chunks=chunks)
        estimated_learning_time = self._resolve_estimated_learning_time(
            lesson=lesson,
            chunks=chunks,
        )
        total_token_length = sum(
            self._estimate_chunk_token_length(str(chunk.get("content") or ""))
            for chunk in chunks
        )
        return lesson_assessment_sizing_service.build_quiz_plan(
            chunk_count=len(chunks),
            total_token_length=total_token_length,
            concept_count=len(lesson_concepts),
            estimated_learning_time=estimated_learning_time,
            concepts=lesson_concepts,
            mastery=mastery,
            requested_target_count=requested_target_count,
        )

    @staticmethod
    def _normalize_requested_question_types(
        question_types: Sequence[str] | None,
    ) -> List[str]:
        del question_types
        return ["multiple_choice"]

    def _decorate_generation_metadata(
        self,
        *,
        metadata: Dict[str, Any],
        assessment_plan: LessonAssessmentSizingResult,
        target_count: int,
    ) -> Dict[str, Any]:
        decorated = dict(metadata or {})
        decorated["lesson_size"] = assessment_plan.lesson_size
        decorated["target_count_auto"] = assessment_plan.target_count_auto
        decorated["target_count_resolved"] = target_count
        decorated["difficulty_distribution"] = assessment_plan.difficulty_distribution
        decorated["bloom_distribution"] = assessment_plan.bloom_distribution
        decorated["lesson_concepts"] = list(assessment_plan.concepts)
        decorated["estimated_learning_time"] = assessment_plan.estimated_learning_time
        decorated["concept_coverage_target"] = dict(
            assessment_plan.coverage_requirement
        )
        return decorated

    @staticmethod
    def compute_runtime_effective_lesson_size(
        declared_lesson_size: str,
        usable_chunk_count: int,
        grounded_content_volume: int,
    ) -> str:
        declared = str(declared_lesson_size or "small").strip().lower()
        usable = max(0, int(usable_chunk_count or 0))
        grounded = max(0, int(grounded_content_volume or 0))
        if declared == "large" and usable <= 2:
            return "small"
        if declared == "large" and usable <= 4:
            return "medium"
        if declared == "medium" and usable <= 2:
            return "small"
        if grounded < 220 and usable <= 2:
            return "small"
        if grounded < 500 and usable <= 4:
            return "medium" if declared == "large" else declared
        return declared if declared in {"small", "medium", "large"} else "small"

    @staticmethod
    def recalculate_target_count_for_degraded_mode(
        lesson_size: str,
        original_target_count: int,
        usable_chunk_count: int,
        mappable_concept_count: int,
        llm_available: bool,
    ) -> int:
        original = max(1, int(original_target_count or 1))
        usable = max(0, int(usable_chunk_count or 0))
        mappable = max(0, int(mappable_concept_count or 0))
        if usable <= 2:
            degraded = min(original, 5)
        elif usable == 3:
            degraded = min(original, 6)
        elif usable in {4, 5}:
            degraded = min(original, 8)
        else:
            degraded = min(original, max(8, usable + min(mappable, 3)))

        fallback_capacity = max(
            1,
            min(
                max(usable * 3, 1),
                max(usable + mappable + 1, 1),
            ),
        )
        if not llm_available:
            degraded = min(degraded, fallback_capacity)
        if lesson_size == "small":
            degraded = min(degraded, max(3, fallback_capacity))
        return max(1, degraded)

    @classmethod
    def _estimate_usable_chunk_count(
        cls,
        chunks: Sequence[Dict[str, Any]],
    ) -> int:
        usable = 0
        for chunk in chunks or []:
            content = str(chunk.get("content") or "").strip()
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            covered_concepts = (
                chunk.get("covered_concepts")
                or metadata.get("covered_concepts")
                or []
            )
            questionability = float(
                chunk.get("questionability_score")
                or metadata.get("questionability_score")
                or 0.0
            )
            word_count = len(content.split())
            if word_count >= 18 or covered_concepts or questionability >= 0.2:
                usable += 1
        return usable

    @staticmethod
    def _estimate_grounded_content_volume(chunks: Sequence[Dict[str, Any]]) -> int:
        return sum(len(str(chunk.get("content") or "").split()) for chunk in chunks or [])

    def _normalize_generation_target_concepts(
        self,
        *,
        raw_target_concepts: Sequence[str],
        context: Dict[str, Any],
        chunks: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        lesson_context = {**context, "chunks": list(chunks or [])}
        normalization = concept_normalization_service.normalize_target_concepts(
            raw_target_concepts=raw_target_concepts,
            lesson_context=lesson_context,
        )
        valid_targets = list(normalization.normalized_target_concepts)
        rejected_targets = list(normalization.rejected_target_concepts)
        concept_mapping_debug = list(normalization.concept_mapping_debug)
        if not valid_targets:
            valid_targets = concept_normalization_service.extract_fallback_target_concepts(
                lesson_context,
                limit=3,
            )
        return {
            "valid_target_concepts": valid_targets,
            "rejected_target_concepts": rejected_targets,
            "concept_mapping_debug": concept_mapping_debug,
        }

    def _resolve_lesson_concepts(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
    ) -> List[str]:
        lesson = context.get("lesson") or {}
        metadata = lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        concepts: List[str] = []
        for value in (
            metadata.get("main_concept"),
            lesson.get("topic"),
        ):
            if value:
                concepts.append(str(value))
        for source in (
            metadata.get("covered_concepts"),
            metadata.get("keywords"),
            lesson.get("learning_objectives"),
            lesson.get("keywords"),
        ):
            if isinstance(source, list):
                concepts.extend(str(item) for item in source)
        for chunk in chunks:
            concepts.extend(
                str(item)
                for item in (
                    chunk.get("covered_concepts")
                    or (
                        (chunk.get("metadata") or {}).get("covered_concepts")
                        if isinstance(chunk.get("metadata"), dict)
                        else []
                    )
                    or []
                )
            )
        return lesson_assessment_sizing_service._normalize_concepts(concepts)

    def _resolve_estimated_learning_time(
        self,
        *,
        lesson: Dict[str, Any],
        chunks: List[Dict[str, Any]],
    ) -> int:
        lesson_metadata = (
            lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        )
        chunk_time = 0.0
        for chunk in chunks:
            chunk_metadata = (
                chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            )
            chunk_time += float(
                chunk.get("estimated_read_time")
                or chunk_metadata.get("estimated_read_time")
                or 0.0
            )
        if chunk_time > 0:
            return max(1, int(round(chunk_time)))
        lesson_time = float(
            lesson_metadata.get("estimated_read_time")
            or lesson_metadata.get("estimated_learning_time")
            or 0.0
        )
        return max(1, int(round(lesson_time))) if lesson_time > 0 else max(1, len(chunks) * 4)

    @staticmethod
    def _estimate_chunk_token_length(content: str) -> int:
        text = str(content or "").strip()
        if not text:
            return 0
        return max(1, int(round(len(text.split()) * 1.3)))

    def _resolve_llm_status_code(
        self,
        *,
        allow_llm: bool,
        llm_debug_status: Dict[str, Any] | None,
        validation: Any | None = None,
    ) -> str:
        if not allow_llm:
            return "disabled"
        debug = llm_debug_status or {}
        last_error = str(
            debug.get("last_error")
            or self.llm_client.get_last_error()
            or ""
        ).strip().lower()
        if bool(debug.get("cooldown_active")):
            return "cooldown"
        if not bool(debug.get("client_available")):
            return "client_unavailable"
        if "quota" in last_error or "resource_exhausted" in last_error or "429" in last_error:
            return "quota_exhausted"
        if validation is None:
            return "available"
        if getattr(validation, "status", "") == "ok":
            return "available"
        if not list(getattr(validation, "questions", []) or []):
            if "empty response" in last_error or "returned an empty response" in last_error:
                return "empty_response"
            return "invalid_response"
        return "available"

    def compute_concept_coverage_rate(
        self,
        questions: Sequence[ValidatedLessonQuestion],
        *,
        valid_target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized_targets = lesson_assessment_sizing_service._normalize_concepts(
            valid_target_concepts or []
        )
        if not normalized_targets:
            return {
                "coverage_rate": None,
                "covered_concepts": [],
                "missing_concepts": [],
                "covered_count": 0,
                "total_concepts": 0,
                "is_valid": False,
                "status": "unavailable_due_to_invalid_targets",
            }

        covered: set[str] = set()
        for concept in normalized_targets:
            for question in questions or []:
                if self._question_covers_canonical_concept(
                    question=question,
                    concept=concept,
                    chunk_map=chunk_map,
                ):
                    covered.add(concept)
                    break

        coverage_rate = len(covered) / max(1, len(normalized_targets))
        status = "covered"
        if coverage_rate < 0.5:
            status = "insufficient_coverage"
        elif coverage_rate < 0.8:
            status = "partial_coverage"
        return {
            "coverage_rate": round(coverage_rate, 4),
            "covered_concepts": sorted(covered),
            "missing_concepts": [
                concept for concept in normalized_targets if concept not in covered
            ],
            "covered_count": len(covered),
            "total_concepts": len(normalized_targets),
            "is_valid": coverage_rate >= 0.8,
            "status": status,
        }

    def _estimate_existing_concept_coverage(
        self,
        *,
        questions: Sequence[Dict[str, Any]],
        valid_target_concepts: Sequence[str],
    ) -> Dict[str, Any]:
        normalized_targets = lesson_assessment_sizing_service._normalize_concepts(
            valid_target_concepts or []
        )
        if not normalized_targets:
            return {"coverage_rate": None, "status": "reused_existing"}
        covered: set[str] = set()
        for question in questions or []:
            metadata = (
                question.get("metadata")
                if isinstance(question.get("metadata"), dict)
                else {}
            )
            candidates = [
                question.get("concept_id"),
                metadata.get("concept_focus"),
                metadata.get("question_focus"),
                *(metadata.get("target_concepts") or []),
                *(metadata.get("matched_target_concepts") or []),
            ]
            normalized_candidates = set(
                lesson_assessment_sizing_service._normalize_concepts(candidates)
            )
            covered.update(
                concept
                for concept in normalized_targets
                if concept in normalized_candidates
            )
        coverage_rate = len(covered) / max(1, len(normalized_targets))
        if coverage_rate >= 0.8:
            status = "reused_existing_covered"
        elif coverage_rate >= 0.5:
            status = "reused_existing_partial_coverage"
        else:
            status = "reused_existing_insufficient_coverage"
        return {
            "coverage_rate": round(coverage_rate, 4),
            "status": status,
            "covered_concepts": sorted(covered),
            "missing_concepts": [
                concept for concept in normalized_targets if concept not in covered
            ],
        }

    @staticmethod
    def _summarize_existing_question_mix(
        questions: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        difficulty_counts: Dict[str, int] = {}
        bloom_counts: Dict[str, int] = {}
        for question in questions or []:
            difficulty = str(question.get("difficulty") or "unknown").strip().lower()
            bloom = str(question.get("bloom_level") or "unknown").strip().lower()
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
            bloom_counts[bloom] = bloom_counts.get(bloom, 0) + 1
        return {
            "difficulty_mix": {"counts": difficulty_counts},
            "bloom_mix": {"counts": bloom_counts},
        }

    def _question_covers_canonical_concept(
        self,
        *,
        question: ValidatedLessonQuestion,
        concept: str,
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> bool:
        normalized_concept = self._normalize_text(concept)
        candidate_texts = self._collect_question_concept_candidates(
            question=question,
            chunk_map=chunk_map,
            include_chunk_content=True,
        )
        normalized_combined = " ".join(candidate_texts).strip()
        if not normalized_combined:
            return False
        if any(
            self._candidate_matches_concept(candidate, normalized_concept)
            for candidate in candidate_texts
        ):
            return True
        semantic_score = self.question_fallback_service.question_nlp_service.semantic_similarity(
            normalized_combined,
            [normalized_concept],
        )
        return semantic_score >= 0.55

    @staticmethod
    def resolve_generation_status(
        *,
        saved_count: int,
        effective_target_count: int,
        concept_coverage_rate: float | None,
        llm_available: bool,
        degraded_mode: bool,
    ) -> str:
        saved = max(0, int(saved_count or 0))
        target = max(1, int(effective_target_count or 1))
        if saved == 0:
            return "failed"
        if saved / max(target, 1) < 0.7:
            return "partial"
        if concept_coverage_rate is not None and float(concept_coverage_rate) < 0.5:
            return "insufficient_coverage"
        if degraded_mode and not llm_available:
            return "degraded_ok"
        return "ok"

    def build_generation_message(
        self,
        *,
        llm_status: str,
        degraded_mode: bool,
        original_target_count: int,
        effective_target_count: int,
        usable_chunk_count: int,
        saved_count: int,
        concept_coverage_rate: float | None,
        concept_coverage_status: str | None,
    ) -> str:
        messages: List[str] = []
        if llm_status in {"cooldown", "quota_exhausted"}:
            messages.append(
                "LLM hiện tạm thời không khả dụng do cooldown quota."
            )
        elif llm_status in {"client_unavailable", "empty_response", "invalid_response"}:
            messages.append(
                "LLM hiện không trả được kết quả ổn định nên hệ thống chuyển sang tạo câu hỏi cục bộ."
            )
        if degraded_mode:
            messages.append(
                f"Hệ thống đã chuyển sang degraded local mode và điều chỉnh số lượng mục tiêu từ {original_target_count} xuống {effective_target_count} dựa trên {usable_chunk_count} chunk đủ tin cậy."
            )
        messages.append(f"Đã tạo {saved_count} câu hỏi.")
        if concept_coverage_status == "unavailable_due_to_invalid_targets":
            messages.append(
                "Không đánh giá được độ bao phủ concept mục tiêu vì target concept ban đầu không hợp lệ; hệ thống đã fallback sang concept của lesson."
            )
        elif concept_coverage_rate is not None:
            if concept_coverage_rate < 0.5:
                messages.append("Độ bao phủ concept hiện chưa đạt yêu cầu.")
            else:
                messages.append(
                    f"Độ bao phủ concept hiện đạt {concept_coverage_rate:.0%}."
                )
        if llm_status in {"cooldown", "quota_exhausted"}:
            messages.append(
                "Khuyến nghị thử lại sau khi dịch vụ AI hồi phục nếu cần bộ câu hỏi đầy đủ hơn."
            )
        return " ".join(messages).strip()

    def _build_generation_next_action(
        self,
        *,
        llm_status: str,
        llm_debug_status: Dict[str, Any],
        concept_coverage_status: str | None,
        degraded_mode: bool,
    ) -> Dict[str, Any]:
        if llm_status in {"cooldown", "quota_exhausted"}:
            return {
                "type": "retry_after_cooldown",
                "retry_after_seconds": int(
                    llm_debug_status.get("cooldown_remaining_seconds", 0) or 0
                ),
            }
        if concept_coverage_status == "insufficient_coverage":
            return {
                "type": "review_lesson_content",
                "reason": "not_enough_grounded_concepts",
            }
        if degraded_mode:
            return {
                "type": "continue_with_degraded_quiz",
                "warning": "local_generation_only",
            }
        return {}

    def _validate_selected_concept_coverage(
        self,
        questions: Sequence[ValidatedLessonQuestion],
        *,
        assessment_plan: LessonAssessmentSizingResult | None,
        required_concepts: Sequence[str] | None = None,
    ) -> Dict[str, Any]:
        normalized_required_concepts = lesson_assessment_sizing_service._normalize_concepts(
            required_concepts or []
        )
        if normalized_required_concepts:
            return lesson_assessment_sizing_service.validate_concept_coverage(
                questions=questions,
                lesson_concepts=normalized_required_concepts,
            )
        if assessment_plan is None:
            return {
                "is_valid": True,
                "coverage_rate": 1.0,
                "missing_concepts": [],
            }
        return lesson_assessment_sizing_service.validate_concept_coverage(
            questions=questions,
            lesson_concepts=assessment_plan.concepts,
        )

    def _build_missing_concept_candidates(
        self,
        *,
        context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        missing_concepts: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        chunk_map: Dict[str, Dict[str, Any]],
        resource_map: Dict[str, Dict[str, Any]],
        score_map: Dict[str, float],
        seen_signatures: set[str],
        generation_metadata: Dict[str, Any],
    ) -> List[ValidatedLessonQuestion]:
        if not missing_concepts or target_count <= 0:
            return []

        target_chunks = [
            chunk
            for chunk in chunks
            if set(
                lesson_assessment_sizing_service._normalize_concepts(
                    chunk.get("covered_concepts")
                    or (
                        (chunk.get("metadata") or {}).get("covered_concepts")
                        if isinstance(chunk.get("metadata"), dict)
                        else []
                    )
                    or []
                )
            ).intersection(set(missing_concepts))
        ]
        coverage_context = {
            **context,
            "target_concepts": list(missing_concepts),
        }
        candidates = self._build_fallback_questions(
            context=coverage_context,
            chunks=target_chunks or chunks,
            target_count=max(target_count, len(missing_concepts)),
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels or ["understand", "apply"],
            relaxed_mode=True,
        )
        enriched: List[ValidatedLessonQuestion] = []
        for candidate in candidates:
            signature = self._question_signature(candidate)
            if not signature or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            enriched.append(
                self._enrich_question_metadata(
                    question=candidate,
                    chunk_map=chunk_map,
                    resource_map=resource_map,
                    score_map=score_map,
                    generation_metadata=generation_metadata,
                    quality_score=self._score_question_quality(
                        candidate, chunk_map=chunk_map, score_map=score_map
                    ),
                )
            )
        return enriched

    def _apply_quiz_distribution_plan(
        self,
        questions: Sequence[ValidatedLessonQuestion],
        *,
        assessment_plan: LessonAssessmentSizingResult | None,
    ) -> List[ValidatedLessonQuestion]:
        finalized = list(questions or [])
        if not finalized or assessment_plan is None:
            return finalized

        bloom_targets = dict(assessment_plan.bloom_distribution.get("counts", {}))
        difficulty_targets = dict(
            assessment_plan.difficulty_distribution.get("counts", {})
        )
        bloom_sequence = self._expand_distribution_sequence(bloom_targets)
        difficulty_sequence = self._expand_distribution_sequence(difficulty_targets)
        finalized.sort(
            key=lambda item: float((item.metadata or {}).get("quality_score", 0.0) or 0.0),
            reverse=True,
        )
        relabeled: List[ValidatedLessonQuestion] = []
        for index, question in enumerate(finalized):
            target_bloom = (
                bloom_sequence[index]
                if index < len(bloom_sequence)
                else question.bloom_level
            )
            target_difficulty_key = (
                difficulty_sequence[index]
                if index < len(difficulty_sequence)
                else lesson_assessment_sizing_service.normalize_difficulty_label(
                    question.difficulty
                )
            )
            metadata = dict(question.metadata or {})
            metadata["original_bloom_level"] = question.bloom_level
            metadata["original_difficulty"] = question.difficulty
            metadata["planned_bloom_level"] = target_bloom
            metadata["planned_difficulty"] = (
                lesson_assessment_sizing_service.denormalize_difficulty_label(
                    target_difficulty_key
                )
            )
            relabeled.append(
                replace(
                    question,
                    bloom_level=target_bloom,
                    difficulty=lesson_assessment_sizing_service.denormalize_difficulty_label(
                        target_difficulty_key
                    ),
                    metadata=metadata,
                )
            )
        return relabeled

    @staticmethod
    def _expand_distribution_sequence(targets: Dict[str, int]) -> List[str]:
        sequence: List[str] = []
        for key, count in targets.items():
            sequence.extend([key] * max(0, int(count or 0)))
        return sequence

    def _extract_question_concepts(self, question: ValidatedLessonQuestion) -> List[str]:
        return lesson_assessment_sizing_service._extract_question_concepts(question)

    def _count_selected_bloom_levels(
        self,
        questions: Sequence[ValidatedLessonQuestion],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for question in questions or []:
            key = str(question.bloom_level or "").strip().lower()
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _count_selected_difficulties(
        self,
        questions: Sequence[ValidatedLessonQuestion],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for question in questions or []:
            key = lesson_assessment_sizing_service.normalize_difficulty_label(
                question.difficulty
            )
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _extract_grounded_evidence(
        self,
        *,
        question: ValidatedLessonQuestion,
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> tuple[str, List[str], float]:
        metadata = question.metadata or {}
        existing_excerpt = str(metadata.get("source_excerpt") or "").strip()
        focus = str(metadata.get("question_focus") or question.correct_answer or "").strip()
        covered_concepts = [
            str(item).strip()
            for item in metadata.get("covered_concepts", [])
            if str(item).strip()
        ]
        search_terms = [
            focus,
            question.correct_answer,
            *covered_concepts[:3],
        ]
        search_terms = [
            term for term in search_terms if self._normalize_text(term)
        ]
        best_excerpt = existing_excerpt
        best_score = self._score_evidence_excerpt(
            excerpt=existing_excerpt,
            question=question,
            search_terms=search_terms,
        )
        best_terms = self._match_terms_in_excerpt(existing_excerpt, search_terms)

        for chunk_id in question.chunk_ids:
            chunk = chunk_map.get(chunk_id) or {}
            content = str(chunk.get("content") or "").strip()
            if not content:
                continue
            candidates = self._candidate_evidence_windows(content)
            for excerpt in candidates:
                score = self._score_evidence_excerpt(
                    excerpt=excerpt,
                    question=question,
                    search_terms=search_terms,
                )
                if score <= best_score:
                    continue
                best_excerpt = excerpt
                best_score = score
                best_terms = self._match_terms_in_excerpt(excerpt, search_terms)

        return best_excerpt, best_terms, round(max(best_score, 0.0), 4)

    def _candidate_evidence_windows(self, content: str) -> List[str]:
        normalized = re.sub(r"\s+", " ", str(content or "")).strip()
        if not normalized:
            return []
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[\.\!\?])\s+", normalized)
            if item.strip()
        ]
        if not sentences:
            return [normalized[:240]]
        windows: List[str] = []
        for index, sentence in enumerate(sentences):
            windows.append(sentence[:260])
            if index + 1 < len(sentences):
                windows.append(f"{sentence} {sentences[index + 1]}"[:260].strip())
        if normalized not in windows:
            windows.append(normalized[:240].strip())
        return windows[:24]

    def _score_evidence_excerpt(
        self,
        *,
        excerpt: str,
        question: ValidatedLessonQuestion,
        search_terms: Sequence[str],
    ) -> float:
        normalized_excerpt = self._normalize_text(excerpt)
        if not normalized_excerpt:
            return -1.0
        score = 0.0
        if 55 <= len(excerpt.strip()) <= 220:
            score += 1.2
        elif len(excerpt.strip()) < 35:
            score -= 0.6
        else:
            score += 0.4

        matches = self._match_terms_in_excerpt(excerpt, search_terms)
        score += len(matches) * 0.75
        if self._normalize_text(question.correct_answer) in normalized_excerpt:
            score += 0.8
        question_focus = self._normalize_text(
            str((question.metadata or {}).get("question_focus") or "")
        )
        if question_focus and question_focus in normalized_excerpt:
            score += 0.9
        if normalized_excerpt.count(":") >= 2 or ">>>" in excerpt:
            score -= 0.8
        return score

    def _match_terms_in_excerpt(
        self, excerpt: str, search_terms: Sequence[str]
    ) -> List[str]:
        normalized_excerpt = self._normalize_text(excerpt)
        matched: List[str] = []
        seen: set[str] = set()
        for term in search_terms:
            normalized = self._normalize_text(term)
            if not normalized or normalized in seen:
                continue
            tokens = [token for token in normalized.split() if len(token) >= 3]
            if not tokens:
                continue
            overlap = sum(1 for token in tokens if token in normalized_excerpt)
            if overlap / max(len(tokens), 1) >= 0.5:
                matched.append(term)
                seen.add(normalized)
        return matched

    def _strengthen_distractors(
        self,
        *,
        question: ValidatedLessonQuestion,
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> tuple[List[str], str]:
        if question.question_type != "multiple_choice":
            return question.distractors, "not_applicable"

        answer_key = self._normalize_text(question.correct_answer)
        existing: List[str] = []
        seen: set[str] = {answer_key}
        for item in question.distractors:
            normalized = self._normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            existing.append(str(item).strip())

        candidate_scores: Dict[str, float] = {}
        focus = str((question.metadata or {}).get("question_focus") or "").strip()
        covered_concepts = [
            str(item).strip()
            for item in (question.metadata or {}).get("covered_concepts", [])
            if str(item).strip()
        ]
        answer_category = self._classify_term(question.correct_answer)

        def add_candidate(raw_value: str, weight: float) -> None:
            candidate = str(raw_value or "").strip()
            normalized = self._normalize_text(candidate)
            if not candidate or normalized in seen:
                return
            if not self._is_domain_term(normalized):
                return
            category = self._classify_term(candidate)
            score = weight
            if category == answer_category:
                score += 0.8
            if focus and normalized == self._normalize_text(focus):
                return
            candidate_scores[candidate] = max(candidate_scores.get(candidate, 0.0), score)

        for concept in covered_concepts:
            add_candidate(concept, 2.2)

        for chunk in chunk_map.values():
            metadata = chunk.get("metadata") or {}
            for concept in metadata.get("covered_concepts") or []:
                add_candidate(str(concept), 1.8)
            content = str(chunk.get("content") or "")
            for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", content):
                add_candidate(token, 0.8)

        for fallback in self._FALLBACK_DISTRACTOR_TERMS():
            add_candidate(fallback, 0.4)

        ordered_candidates = [
            candidate
            for candidate, _ in sorted(
                candidate_scores.items(),
                key=lambda item: (-item[1], len(item[0])),
            )
        ]
        improved = list(existing)
        for candidate in ordered_candidates:
            normalized = self._normalize_text(candidate)
            if normalized in {self._normalize_text(item) for item in improved}:
                continue
            improved.append(candidate)
            if len(improved) >= 3:
                break

        strategy = "existing"
        if len(improved) >= 3 and improved[:3] != list(question.distractors[:3]):
            strategy = "lesson_contrast_pool"
        return improved[:3], strategy

    @classmethod
    def _FALLBACK_DISTRACTOR_TERMS(cls) -> List[str]:
        return list(cls._FALLBACK_DISTRACTORS)

    def _enrich_question_metadata(
        self,
        *,
        question: ValidatedLessonQuestion,
        chunk_map: Dict[str, Dict[str, Any]],
        resource_map: Dict[str, Dict[str, Any]],
        score_map: Dict[str, float],
        generation_metadata: Dict[str, Any],
        quality_score: float,
    ) -> ValidatedLessonQuestion:
        metadata = dict(question.metadata or {})
        target_concepts = self._extract_target_concepts(generation_metadata)
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
        if target_concepts:
            metadata.setdefault("target_concepts", list(target_concepts))
        strengthened_distractors, distractor_strategy = self._strengthen_distractors(
            question=question,
            chunk_map=chunk_map,
        )
        evidence_excerpt, evidence_terms, evidence_score = self._extract_grounded_evidence(
            question=question,
            chunk_map=chunk_map,
        )
        if evidence_excerpt:
            metadata["source_excerpt"] = evidence_excerpt
        if evidence_terms:
            metadata["evidence_terms"] = evidence_terms
        metadata["evidence_score"] = evidence_score
        metadata["distractor_strategy"] = distractor_strategy
        matched_target_concepts = self._resolve_matched_target_concepts(
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )
        metadata["matched_target_concepts"] = matched_target_concepts
        if matched_target_concepts and not str(metadata.get("concept_focus") or "").strip():
            metadata["concept_focus"] = matched_target_concepts[0]
        metadata["target_concept_match"] = bool(matched_target_concepts)
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

        provisional_question = ValidatedLessonQuestion(
            question_type=question.question_type,
            question=question.question,
            correct_answer=question.correct_answer,
            distractors=strengthened_distractors,
            explanation=question.explanation,
            difficulty=question.difficulty,
            bloom_level=question.bloom_level,
            chunk_ids=question.chunk_ids,
            metadata=metadata,
        )
        improved_quality_score = self._score_question_quality(
            provisional_question,
            chunk_map=chunk_map,
            score_map=score_map,
        )
        metadata["quality_score"] = round(float(max(quality_score, improved_quality_score)), 4)
        metadata["confidence_score"] = self._compute_confidence_score(
            question=provisional_question,
            quality_score=float(metadata["quality_score"]),
            max_chunk_score=max(source_scores.values(), default=0.0),
        )

        return ValidatedLessonQuestion(
            question_type=question.question_type,
            question=question.question,
            correct_answer=question.correct_answer,
            distractors=strengthened_distractors,
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
        reasoning_pattern = str(question.metadata.get("reasoning_pattern") or "").strip()
        distractor_rationale = [
            str(item).strip()
            for item in (question.metadata.get("distractor_rationale") or [])
            if str(item).strip()
        ]
        evidence_terms = [
            str(item).strip()
            for item in (question.metadata.get("evidence_terms") or [])
            if str(item).strip()
        ]
        evidence_score = float(question.metadata.get("evidence_score", 0.0) or 0.0)
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
        score += min(evidence_score, 4.0) * 0.2

        if question_focus:
            score += 0.35
            if self._normalize_text(question_focus) in self._AMBIGUOUS_TERMS:
                score -= 0.3
        if bool(question.metadata.get("target_concept_match")):
            score += 0.55
        if reasoning_pattern:
            score += 0.22
            if reasoning_pattern in {
                "worked_example",
                "decision_rule",
                "error_detection",
                "compare_contrast",
            }:
                score += 0.12
        score += min(len(evidence_terms), 3) * 0.06

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
            if len(distractor_rationale) == 3:
                score += 0.18
            if str(question.metadata.get("distractor_strategy") or "") == "lesson_contrast_pool":
                score += 0.35
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

        score -= self._surface_level_penalty(question)
        if self._has_reasoning_depth_signal(question.question):
            score += 0.3

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

    def _surface_level_penalty(self, question: ValidatedLessonQuestion) -> float:
        normalized_question = self._normalize_text(question.question)
        normalized_answer = self._normalize_text(question.correct_answer)
        normalized_focus = self._normalize_text(
            str((question.metadata or {}).get("question_focus") or "")
        )
        penalty = 0.0
        if normalized_answer and normalized_answer in normalized_question:
            penalty += 1.1
        shallow_prefixes = {
            "khai niem nao",
            "dap an nao",
            "nêu",
            "nhac lai",
            "đáp án nào",
            "khái niệm nào",
            "nhắc lại",
        }
        if any(normalized_question.startswith(prefix) for prefix in shallow_prefixes):
            penalty += 0.35
        if len(normalized_question) < 34:
            penalty += 0.2
        if normalized_focus and normalized_focus in self._AMBIGUOUS_TERMS:
            penalty += 0.18
        if (
            question.bloom_level in {"apply", "analyze", "evaluate", "create"}
            and not self._has_reasoning_depth_signal(question.question)
        ):
            penalty += 0.42
        return penalty

    @staticmethod
    def _has_reasoning_depth_signal(question_text: str) -> bool:
        normalized = " ".join(str(question_text or "").strip().lower().split())
        if not normalized:
            return False
        markers = (
            "trong tình huống",
            "trong truong hop",
            "trường hợp",
            "vì sao",
            "vi sao",
            "so sánh",
            "so sanh",
            "kết quả nào",
            "ket qua nao",
            "phân tích",
            "phan tich",
            "bước nào",
            "buoc nao",
            "quyết định nào",
            "quyet dinh nao",
        )
        return any(marker in normalized for marker in markers)

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
        evidence_signal = max(
            0.0,
            min(1.0, float(question.metadata.get("evidence_score", 0.0) or 0.0) / 4.0),
        )
        distractor_quality = 0.0
        if question.question_type == "multiple_choice":
            unique_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            distractor_quality = max(0.0, min(1.0, len(unique_choices) / 4.0))
            if str(question.metadata.get("distractor_strategy") or "") == "lesson_contrast_pool":
                distractor_quality = min(1.0, distractor_quality + 0.15)
        elif question.question_type == "short_answer":
            distractor_quality = 0.7
        else:
            distractor_quality = 0.6
        weighted = (
            QUESTION_CONFIDENCE_BASELINE
            + normalized_quality * 0.34
            + normalized_chunk * 0.20
            + coverage * 0.16
            + distractor_quality * 0.14
            + evidence_signal * 0.16
        )
        return round(max(0.0, min(1.0, weighted)), 4)

    def _is_low_quality_local_question(
        self, question: ValidatedLessonQuestion
    ) -> bool:
        generation_mode = str(question.metadata.get("generation_mode") or "").strip()
        if generation_mode not in {"local_fallback", "local_fill"}:
            return False

        source_excerpt = str(question.metadata.get("source_excerpt") or "").strip()
        normalized_excerpt = self._normalize_text(source_excerpt)
        question_focus = str(
            question.metadata.get("question_focus") or question.correct_answer
        ).strip()
        normalized_focus = self._normalize_text(question_focus)
        normalized_answer = self._normalize_text(question.correct_answer)
        normalized_question = self._normalize_text(question.question)
        fallback_score = float(question.metadata.get("fallback_excerpt_score", 0.0) or 0.0)
        is_functional_claim = (
            question.question_type == "multiple_choice"
            and "mo ta dung nhat" in normalized_question
            and normalized_answer.startswith(("dung de ", "cho phep ", "giup ", "co the ", "la "))
        )
        is_descriptive_fallback = (
            question.question_type == "multiple_choice"
            and (
                "theo noi dung bai hoc" in normalized_question
                or "trong vi du cua bai hoc" in normalized_question
                or "theo phan gioi thieu cua bai hoc" in normalized_question
                or "theo phan tom tat cua bai hoc" in normalized_question
            )
            and len(normalized_answer) >= 12
        )

        minimum_excerpt_score = 0.35 if is_functional_claim else 0.75
        if source_excerpt and fallback_score and fallback_score < minimum_excerpt_score:
            return True
        if normalized_excerpt.startswith("example "):
            return True
        if ">>>" in source_excerpt or normalized_excerpt.count(":") >= 2:
            return True
        if re.search(r"\b(serial|twitter|affiliation|venue|venues|record|records)\b", normalized_excerpt):
            return True
        if (
            not is_descriptive_fallback
            and (
                normalized_focus in self._AMBIGUOUS_TERMS
                or normalized_answer in self._AMBIGUOUS_TERMS
            )
        ):
            return True
        if (
            not is_descriptive_fallback
            and (
                normalized_focus in self._FALLBACK_STOP_WORDS
                or normalized_answer in self._FALLBACK_STOP_WORDS
            )
        ):
            return True
        if (
            not is_functional_claim
            and not is_descriptive_fallback
            and not self._is_domain_term(normalized_focus)
            and not self._is_domain_term(normalized_answer)
        ):
            return True
        if question.question_type == "true_false" and (
            not self._is_reinforcement_true_false_safe(
                statement=source_excerpt or question.question,
                focus=question_focus,
            )
        ):
            return True
        if question.question_type == "multiple_choice":
            normalized_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            if len(normalized_choices) < 4:
                return True
            if is_descriptive_fallback and len(normalized_answer) >= 12:
                return False
        return False

    def _is_salvageable_local_question(
        self, question: ValidatedLessonQuestion
    ) -> bool:
        generation_mode = str(question.metadata.get("generation_mode") or "").strip()
        if generation_mode not in {"local_fallback", "local_fill"}:
            return False

        source_excerpt = str(question.metadata.get("source_excerpt") or "").strip()
        normalized_excerpt = self._normalize_text(source_excerpt)
        normalized_question = self._normalize_text(question.question)
        normalized_answer = self._normalize_text(question.correct_answer)

        if not normalized_question or not normalized_answer:
            return False
        if normalized_excerpt.startswith("example "):
            return False
        if ">>>" in source_excerpt or normalized_excerpt.count(":") >= 2:
            return False
        if re.search(
            r"\b(serial|twitter|affiliation|venue|venues|record|records)\b",
            normalized_excerpt,
        ):
            return False
        if question.question_type == "true_false":
            return self._is_reinforcement_true_false_safe(
                statement=source_excerpt or question.question,
                focus=str(question.metadata.get("question_focus") or question.correct_answer),
            )
        if question.question_type == "multiple_choice":
            normalized_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            return len(normalized_choices) == 4
        return len(normalized_answer) >= 8

    def _extend_with_salvageable_local_questions(
        self,
        *,
        current_questions: List[ValidatedLessonQuestion],
        source_questions: List[ValidatedLessonQuestion],
        target_count: int,
    ) -> List[ValidatedLessonQuestion]:
        if len(current_questions) >= target_count:
            return list(current_questions[:target_count])

        extended = list(current_questions)
        seen_signatures = {
            self._question_signature(item)
            for item in extended
            if self._question_signature(item)
        }
        for item in source_questions:
            if len(extended) >= target_count:
                break
            signature = self._question_signature(item)
            if not signature or signature in seen_signatures:
                continue
            if not self._is_salvageable_local_question(item):
                continue
            seen_signatures.add(signature)
            extended.append(item)
        return extended[:target_count]

    def _is_degraded_fill_candidate(
        self,
        question: ValidatedLessonQuestion,
    ) -> bool:
        normalized_question = self._normalize_text(question.question)
        normalized_answer = self._normalize_text(question.correct_answer)
        if not normalized_question or not normalized_answer:
            return False

        if question.question_type == "multiple_choice":
            normalized_choices = {
                self._normalize_text(item)
                for item in [question.correct_answer, *question.distractors]
                if self._normalize_text(item)
            }
            if len(normalized_choices) < 4:
                return False

        generation_mode = str(question.metadata.get("generation_mode") or "").strip().lower()
        if generation_mode in {"local_fallback", "local_fill"}:
            return self._is_salvageable_local_question(question)
        return True

    def _extend_with_degraded_fill_candidates(
        self,
        *,
        current_questions: List[ValidatedLessonQuestion],
        source_questions: List[ValidatedLessonQuestion],
        target_count: int,
    ) -> List[ValidatedLessonQuestion]:
        if len(current_questions) >= target_count:
            return list(current_questions[:target_count])

        extended = list(current_questions)
        seen_signatures = {
            self._question_signature(item)
            for item in extended
            if self._question_signature(item)
        }

        for item in source_questions:
            if len(extended) >= target_count:
                break
            signature = self._question_signature(item)
            if not signature or signature in seen_signatures:
                continue
            if not self._is_degraded_fill_candidate(item):
                continue
            seen_signatures.add(signature)
            metadata = dict(item.metadata or {})
            metadata["degraded_fill_candidate"] = True
            extended.append(replace(item, metadata=metadata))

        return extended[:target_count]

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
        return self._question_signature_from_parts(
            question_text=question.question,
            correct_answer=question.correct_answer,
        )

    def _question_signature_from_parts(
        self, *, question_text: Any, correct_answer: Any
    ) -> str:
        stem = self._normalize_text(question_text)
        answer = self._normalize_text(correct_answer)
        if not stem:
            return ""
        return f"{stem}::{answer}"

    def _collect_excluded_question_signatures(
        self,
        *,
        existing_questions: Sequence[Dict[str, Any]] | None,
        generation_metadata: Dict[str, Any] | None,
    ) -> set[str]:
        signatures: set[str] = set()
        for item in existing_questions or []:
            signature = self._question_signature_from_parts(
                question_text=item.get("question"),
                correct_answer=item.get("correct_answer"),
            )
            if signature:
                signatures.add(signature)

        metadata = generation_metadata if isinstance(generation_metadata, dict) else {}
        previous_questions = metadata.get("previous_questions")
        if not isinstance(previous_questions, list):
            previous_questions = (
                metadata.get("generation_strategy", {}).get("previous_questions")
                if isinstance(metadata.get("generation_strategy"), dict)
                else []
            )

        for item in previous_questions or []:
            if not isinstance(item, dict):
                continue
            signature = self._question_signature_from_parts(
                question_text=item.get("question"),
                correct_answer=item.get("correct_answer"),
            )
            if signature:
                signatures.add(signature)
        return signatures

    def _build_semantic_dedup_text(self, question: ValidatedLessonQuestion) -> str:
        metadata = question.metadata or {}
        focus = str(
            metadata.get("concept_focus")
            or metadata.get("question_focus")
            or ""
        ).strip()
        source_excerpt = str(metadata.get("source_excerpt") or "").strip()
        parts = [
            str(question.question_type or "").strip(),
            str(question.question or "").strip(),
            str(question.correct_answer or "").strip(),
            focus,
            source_excerpt[:240],
        ]
        return " | ".join(part for part in parts if part)

    @staticmethod
    def _concept_sets_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
        left_set = set(lesson_assessment_sizing_service._normalize_concepts(left))
        right_set = set(lesson_assessment_sizing_service._normalize_concepts(right))
        if not left_set or not right_set:
            return True
        return bool(left_set.intersection(right_set))

    def _semantic_deduplicate_candidates(
        self,
        *,
        context: Dict[str, Any],
        questions: Sequence[ValidatedLessonQuestion],
        target_concepts: Sequence[str],
    ) -> tuple[List[ValidatedLessonQuestion], int]:
        if not QUESTION_SEMANTIC_DEDUP_ENABLED or not questions:
            return list(questions), 0

        semantic_texts = [self._build_semantic_dedup_text(question) for question in questions]
        embeddings = embedding_service.embed_texts(semantic_texts)
        subject_id = str((context.get("subject") or {}).get("_id") or "").strip()
        lesson_id = str((context.get("lesson") or {}).get("_id") or "").strip()
        memory_candidates = self.question_semantic_memory_repository.find_candidates(
            subject_id=subject_id,
            exclude_lesson_id=lesson_id,
            concept_ids=target_concepts,
            limit=QUESTION_SEMANTIC_DEDUP_LOOKBACK,
        )

        external_vectors: List[tuple[np.ndarray, List[str], str]] = []
        for item in memory_candidates:
            raw_embedding = item.get("embedding") or []
            if not isinstance(raw_embedding, list) or not raw_embedding:
                continue
            try:
                vector = np.array(raw_embedding, dtype=float)
            except Exception:
                continue
            external_vectors.append(
                (
                    vector,
                    [str(value) for value in (item.get("concept_ids") or [])],
                    str(item.get("question_id") or "").strip(),
                )
            )

        kept: List[ValidatedLessonQuestion] = []
        kept_vectors: List[tuple[np.ndarray, List[str], str]] = []
        filtered = 0

        for question, semantic_text, embedding in zip(questions, semantic_texts, embeddings):
            try:
                candidate_vector = np.array(embedding, dtype=float)
            except Exception:
                kept.append(question)
                continue

            question_concepts = self._extract_question_concepts(question)
            duplicate_score = 0.0
            duplicate_source = ""

            for existing_vector, existing_concepts, existing_question_id in external_vectors:
                if not self._concept_sets_overlap(question_concepts, existing_concepts):
                    continue
                similarity = cosine_similarity(candidate_vector, existing_vector)
                if similarity >= QUESTION_SEMANTIC_DEDUP_THRESHOLD:
                    duplicate_score = similarity
                    duplicate_source = f"memory:{existing_question_id}" if existing_question_id else "memory"
                    break

            if not duplicate_source:
                for kept_vector, kept_concepts, kept_signature in kept_vectors:
                    if not self._concept_sets_overlap(question_concepts, kept_concepts):
                        continue
                    similarity = cosine_similarity(candidate_vector, kept_vector)
                    if similarity >= QUESTION_SEMANTIC_DEDUP_THRESHOLD:
                        duplicate_score = similarity
                        duplicate_source = f"batch:{kept_signature}" if kept_signature else "batch"
                        break

            if duplicate_source:
                question.metadata["semantic_duplicate_score"] = round(float(duplicate_score), 4)
                question.metadata["semantic_duplicate_source"] = duplicate_source
                filtered += 1
                continue

            question.metadata["semantic_text"] = semantic_text
            kept.append(question)
            kept_vectors.append(
                (
                    candidate_vector,
                    question_concepts,
                    self._question_signature(question),
                )
            )

        if not kept and questions:
            fallback_question = list(questions)[0]
            fallback_question.metadata["semantic_text"] = semantic_texts[0]
            kept = [fallback_question]
            filtered = max(0, filtered - 1)
        return kept, filtered

    def _persist_question_semantic_memory(
        self,
        *,
        question_ids: Sequence[str],
        questions: Sequence[ValidatedLessonQuestion],
        context: Dict[str, Any],
    ) -> int:
        if not question_ids or not questions:
            return 0

        semantic_texts = [
            str((question.metadata or {}).get("semantic_text") or "").strip()
            or self._build_semantic_dedup_text(question)
            for question in questions
        ]
        embeddings = embedding_service.embed_texts(semantic_texts)
        records: List[Dict[str, Any]] = []
        for question_id, question, semantic_text, embedding in zip(
            question_ids,
            questions,
            semantic_texts,
            embeddings,
        ):
            records.append(
                {
                    "question_id": str(question_id),
                    "subject_id": str((context.get("subject") or {}).get("_id") or ""),
                    "chapter_id": str((context.get("chapter") or {}).get("_id") or ""),
                    "lesson_id": str((context.get("lesson") or {}).get("_id") or ""),
                    "question_type": str(question.question_type or ""),
                    "concept_ids": self._extract_question_concepts(question),
                    "semantic_text": semantic_text,
                    "embedding": embedding,
                }
            )
        return self.question_semantic_memory_repository.insert_many(records)

    def _verify_candidate_questions(
        self,
        *,
        questions: Sequence[ValidatedLessonQuestion],
        target_concepts: Sequence[str],
        requested_bloom_levels: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> tuple[List[ValidatedLessonQuestion], int, Dict[str, Any]]:
        if not questions:
            return [], 0, {"checked_count": 0, "passed_count": 0, "hard_fail_count": 0, "blocker_counts": {}}

        verified: List[ValidatedLessonQuestion] = []
        rejected: List[ValidatedLessonQuestion] = []
        filtered = 0
        blocker_counts: Dict[str, int] = {}

        for question in questions:
            result = question_cross_verification_service.verify_question(
                question=question,
                target_concepts=target_concepts,
                requested_bloom_levels=requested_bloom_levels,
                chunk_map=chunk_map,
            )
            metadata = dict(question.metadata or {})
            existing_matches = [
                str(value).strip()
                for value in (metadata.get("matched_target_concepts") or [])
                if str(value).strip()
            ]
            merged_matches = lesson_assessment_sizing_service._normalize_concepts(
                [*existing_matches, *result.matched_target_concepts]
            )
            metadata["matched_target_concepts"] = merged_matches
            metadata["target_concept_match"] = bool(merged_matches)
            metadata["verification_score"] = result.overall_score
            metadata["verification_pass"] = result.passed
            metadata["verification_hard_fail"] = result.hard_fail
            metadata["verification_blockers"] = list(result.blockers)
            metadata["verification_checks"] = {
                "concept_alignment": result.concept_score,
                "bloom_alignment": result.bloom_score,
                "distractor_quality": result.distractor_score,
                "grounding_quality": result.grounding_score,
                "stem_quality": result.stem_score,
            }
            metadata["predicted_bloom_level"] = result.predicted_bloom_level
            if merged_matches and not str(metadata.get("concept_focus") or "").strip():
                metadata["concept_focus"] = merged_matches[0]
            for blocker in result.blockers:
                blocker_key = self._normalize_text(str(blocker or ""))
                if blocker_key:
                    blocker_counts[blocker_key] = blocker_counts.get(blocker_key, 0) + 1

            enriched_question = replace(question, metadata=metadata)
            if result.hard_fail:
                rejected.append(enriched_question)
                filtered += 1
                continue
            verified.append(enriched_question)
        diagnostics = {
            "checked_count": len(list(questions or [])),
            "passed_count": len(verified),
            "hard_fail_count": len(rejected),
            "blocker_counts": blocker_counts,
        }
        return verified, filtered, diagnostics

    @staticmethod
    def _determine_generation_mode(questions: List[ValidatedLessonQuestion]) -> str:
        if not questions:
            return "empty"
        generation_modes = {
            str(question.metadata.get("generation_mode") or "llm")
            for question in questions
        }
        if generation_modes <= {"local_fallback", "local_fill"}:
            return "local_fallback"
        if "local_fallback" in generation_modes or "local_fill" in generation_modes:
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
        cache_stats: Dict[str, Any] | None = None,
        runtime_details: Dict[str, Any] | None = None,
    ) -> None:
        extra_error = f" | llm_error={llm_error}" if llm_error else ""
        extra_cache = ""
        if cache_stats:
            extra_cache = (
                " | cache_hits=%s | cache_misses=%s | cache_hit_rate=%s | cache_entries=%s"
                % (
                    cache_stats.get("hits", 0),
                    cache_stats.get("misses", 0),
                    cache_stats.get("request_hit_rate", cache_stats.get("hit_rate", 0.0)),
                    cache_stats.get("entries", 0),
                )
            )
        extra_runtime = ""
        if runtime_details:
            runtime_parts = [
                f"{key}={value}"
                for key, value in runtime_details.items()
                if value is not None and value != []
            ]
            if runtime_parts:
                extra_runtime = " | " + " | ".join(runtime_parts)
        logger.info(
            "lesson_question_generation | lesson_id=%s | status=%s | mode=%s | questions=%s | chunks=%s | covered_chunks=%s | message=%s%s%s%s",
            lesson_id,
            status,
            generation_mode,
            question_count,
            chunk_count,
            covered_chunk_count,
            message,
            extra_error,
            extra_cache,
            extra_runtime,
        )

    def _resolve_recommendation(
        self, lesson_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id)
        if recommendation:
            return recommendation

        fallback_payload = self._build_recommendation_fallback_payload(
            lesson_id=lesson_id,
            context=context,
        )
        if not fallback_payload:
            return None
        return self.recommendation_repository.upsert_for_lesson(
            lesson_id, fallback_payload
        )

    def _peek_recommendation(
        self, lesson_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id)
        if recommendation:
            return recommendation

        return self._build_recommendation_fallback_payload(
            lesson_id=lesson_id,
            context=context,
        )

    def _build_recommendation_fallback_payload(
        self, *, lesson_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        lesson = context.get("lesson") or self.lesson_repository.get(lesson_id)
        if not lesson:
            return None

        subject = context.get("subject") or {}
        chapter = context.get("chapter") or {}
        if not subject or not chapter:
            return None

        chunk_ids = lesson.get("recommended_chunk_ids") or []
        if not chunk_ids:
            return None

        resource_ids = lesson.get("recommended_resource_ids") or []
        fallback_payload = {
            "subject_id": subject["_id"],
            "chapter_id": chapter["_id"],
            "lesson_id": lesson["_id"],
            "chunk_ids": list(chunk_ids),
            "resource_ids": list(resource_ids),
            "selection_strategy": "lesson_document_fallback_v1",
            "metadata": {
                "source": "lesson_document_fallback",
                "selected_count": len(chunk_ids),
            },
        }
        return fallback_payload

    def _recommendation_covers_target_concepts(
        self,
        *,
        recommendation: Dict[str, Any] | None,
        target_concepts: Sequence[str],
    ) -> bool:
        normalized_targets = self._extract_target_concepts(
            {"target_concepts": list(target_concepts or [])}
        )
        if not normalized_targets:
            return True
        if not recommendation:
            return False

        sequence_metadata = recommendation.get("sequence_metadata") or {}
        covered_required = self._extract_target_concepts(
            {
                "target_concepts": list(
                    sequence_metadata.get("covered_required_concepts")
                    or sequence_metadata.get("required_concepts")
                    or []
                )
            }
        )
        if any(target in covered_required for target in normalized_targets):
            return True

        for chunk in recommendation.get("recommended_chunks") or []:
            covered = self._extract_target_concepts(
                {"target_concepts": list(chunk.get("covered_concepts") or [])}
            )
            if any(target in covered for target in normalized_targets):
                return True
        return False

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

    def _build_local_context_generation_scope(
        self,
        *,
        lesson_id: str,
        context: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        lesson = context.get("lesson") or {}
        metadata = (
            lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        )
        local_chunk_id = f"local_context_{lesson_id}"
        target_concepts = list(
            metadata.get("target_concepts")
            or metadata.get("covered_concepts")
            or lesson.get("keywords")
            or []
        )
        content = " ".join(
            str(item or "").strip()
            for item in [
                lesson.get("title"),
                lesson.get("summary"),
                " ".join(
                    str(value) for value in lesson.get("learning_objectives") or []
                ),
                " ".join(str(value) for value in target_concepts),
            ]
            if str(item or "").strip()
        )
        if not content:
            content = "Lesson context is unavailable; generate a basic review question."
        chunk = {
            "_id": local_chunk_id,
            "resource_id": None,
            "chunk_index": 0,
            "content": content,
            "covered_concepts": target_concepts,
            "matched_required_concepts": target_concepts,
            "questionability_score": 0.25,
            "metadata": {
                "source": "lesson_local_context",
                "covered_concepts": target_concepts,
                "degraded_mode": True,
                "degraded_reason": "no_recommended_chunks",
            },
        }
        recommendation = {
            "_id": f"local_recommendation_{lesson_id}",
            "lesson_id": lesson.get("_id") or lesson_id,
            "chunk_ids": [local_chunk_id],
            "resource_ids": [],
            "selection_strategy": "local_context_no_chunks_v1",
            "metadata": {
                "source": "local_context_fallback",
                "degraded_mode": True,
                "degraded_reason": "no_recommended_chunks",
                "selected_count": 1,
            },
            "sequence_metadata": {
                "required_concepts": target_concepts,
                "covered_required_concepts": target_concepts,
                "missing_required_concepts": [],
            },
            "recommended_chunks": [
                {
                    "chunk_id": local_chunk_id,
                    "resource_id": None,
                    "chunk_index": 0,
                    "covered_concepts": target_concepts,
                    "matched_required_concepts": target_concepts,
                    "questionability_score": 0.25,
                    "estimated_read_time": 1,
                    "score": 0.0,
                }
            ],
        }
        logger.warning(
            "lesson_question_generation_no_chunks_local_context | lesson_id=%s",
            lesson_id,
        )
        return recommendation, [local_chunk_id], [chunk]

    @staticmethod
    def _resolve_bloom_levels_for_difficulty(
        *,
        difficulty: str,
        bloom_levels: Sequence[str],
        target_count: int,
    ) -> List[str]:
        requested = [
            str(item or "").strip().lower()
            for item in bloom_levels or []
            if str(item or "").strip()
        ]
        level = str(difficulty or "beginner").strip().lower()
        if level == "advanced":
            preferred = ["analyze", "evaluate", "create", "apply"]
        elif level == "intermediate":
            preferred = ["understand", "apply", "analyze"]
        else:
            preferred = ["remember", "understand", "apply"]
        merged: List[str] = []
        for item in [*requested, *preferred]:
            if item and item not in merged:
                merged.append(item)
        minimum_diversity = min(max(1, int(target_count or 1)), len(preferred))
        for item in preferred:
            if len(merged) >= minimum_diversity:
                break
            if item not in merged:
                merged.append(item)
        return merged or preferred[:minimum_diversity]

    @staticmethod
    def _build_bloom_distribution(
        *,
        target_count: int,
        lesson_size: str,
        bloom_levels: Sequence[str],
    ) -> Dict[str, Any]:
        normalized = [
            str(item or "").strip().lower()
            for item in bloom_levels or []
            if str(item or "").strip()
        ]
        if not normalized:
            return lesson_assessment_sizing_service.compute_bloom_distribution(
                target_count=target_count,
                lesson_size=lesson_size,
            )
        bounded_target = max(1, int(target_count or 1))
        counts = {level: 0 for level in normalized}
        for index in range(bounded_target):
            counts[normalized[index % len(normalized)]] += 1
        return {
            "ratios": {
                level: round(count / bounded_target, 4)
                for level, count in counts.items()
            },
            "counts": counts,
        }

    @staticmethod
    def _enrich_chunks_with_recommendation_metadata(
        *,
        chunks: List[Dict[str, Any]],
        recommendation: Dict[str, Any] | None,
    ) -> List[Dict[str, Any]]:
        recommended_chunk_map = {
            str(item.get("chunk_id") or ""): item
            for item in (recommendation or {}).get("recommended_chunks", [])
            if str(item.get("chunk_id") or "").strip()
        }
        enriched: List[Dict[str, Any]] = []
        for chunk in chunks:
            chunk_id = str(chunk.get("_id") or "")
            metadata = recommended_chunk_map.get(chunk_id, {})
            chunk_copy = dict(chunk)
            if metadata:
                matched_required_concepts = [
                    str(item).strip()
                    for item in (metadata.get("matched_required_concepts") or [])
                    if str(item).strip()
                ]
                covered_concepts = [
                    str(item).strip()
                    for item in (metadata.get("covered_concepts") or [])
                    if str(item).strip()
                ]
                combined_concepts = lesson_assessment_sizing_service._normalize_concepts(
                    [*covered_concepts, *matched_required_concepts]
                )
                chunk_copy["instruction_role"] = str(
                    metadata.get("instruction_role")
                    or chunk_copy.get("instruction_role")
                    or "explanation"
                )
                chunk_copy["covered_concepts"] = combined_concepts
                chunk_copy["matched_required_concepts"] = matched_required_concepts
                chunk_copy["questionability_score"] = float(
                    metadata.get("questionability_score", 0.0) or 0.0
                )
                chunk_copy["estimated_read_time"] = int(
                    metadata.get("estimated_read_time", 0) or 0
                )
            enriched.append(chunk_copy)
        return enriched

    def _run_generation(
        self,
        *,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ):
        recommended_chunk_map = {
            str(item.get("chunk_id") or ""): item
            for item in (recommendation or {}).get("recommended_chunks", [])
            if str(item.get("chunk_id") or "").strip()
        }
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
                "resource_id": str(chunk.get("resource_id") or ""),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "page_number": self.lesson_chunk_service._resolve_page_number(chunk),
                "resource_title": str(
                    resource_map.get(str(chunk.get("resource_id") or ""), {}).get("title") or ""
                ),
                "resource_source": str(
                    resource_map.get(str(chunk.get("resource_id") or ""), {}).get("source") or ""
                ),
                "score": float(
                    context.get("recommendation_scores", {}).get(str(chunk["_id"]), 0.0)
                    if isinstance(context.get("recommendation_scores"), dict)
                    else 0.0
                ),
                "instruction_role": str(
                    recommended_chunk_map.get(str(chunk["_id"]), {}).get(
                        "instruction_role"
                    )
                    or "explanation"
                ),
                "covered_concepts": [
                    str(item)
                    for item in (
                        recommended_chunk_map.get(str(chunk["_id"]), {}).get(
                            "covered_concepts"
                        )
                        or []
                    )
                    if str(item).strip()
                ],
                "questionability_score": float(
                    recommended_chunk_map.get(str(chunk["_id"]), {}).get(
                        "questionability_score",
                        0.0,
                    )
                    or 0.0
                ),
                "estimated_read_time": int(
                    recommended_chunk_map.get(str(chunk["_id"]), {}).get(
                        "estimated_read_time",
                        0,
                    )
                    or 0
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

    def _acquire_inflight_generation_request(
        self, request_key: str
    ) -> tuple[Dict[str, Any], bool]:
        with self._inflight_generation_lock:
            current = self._inflight_generation_requests.get(request_key)
            if current is not None:
                return current, False
            created = {"event": Event(), "result": None, "error": None}
            self._inflight_generation_requests[request_key] = created
            return created, True

    def _build_generation_request_key(
        self,
        *,
        lesson_id: str,
        target_count: int | None,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        allow_llm: bool,
        mastery: float | None,
        success_rate: float | None,
        overwrite: bool,
        metadata: Dict[str, Any],
    ) -> str:
        canonical_payload = {
            "lesson_id": str(lesson_id or "").strip(),
            "target_count": int(target_count) if target_count is not None else None,
            "question_types": sorted(
                str(item).strip().lower() for item in question_types if str(item).strip()
            ),
            "difficulty": str(difficulty or "").strip().lower(),
            "bloom_levels": sorted(
                str(item).strip().lower() for item in bloom_levels if str(item).strip()
            ),
            "allow_llm": bool(allow_llm),
            "mastery": None if mastery is None else round(float(mastery), 4),
            "success_rate": (
                None if success_rate is None else round(float(success_rate), 4)
            ),
            "overwrite": bool(overwrite),
            "metadata": metadata or {},
        }
        raw = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

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

    def _ensure_generation_recommendation(
        self,
        *,
        lesson_id: str,
        context: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        recommendation = self._resolve_recommendation(lesson_id, context)
        if recommendation and list(recommendation.get("chunk_ids") or []):
            return recommendation

        refreshed = self._refresh_recommendation(
            lesson_id=lesson_id,
            metadata={
                **metadata,
                "trigger": "question_generation_missing_recommendation",
            },
        )
        if refreshed and list(refreshed.get("chunk_ids") or []):
            return refreshed

        fallback_recommendation = self._resolve_recommendation(lesson_id, context)
        if fallback_recommendation and list(fallback_recommendation.get("chunk_ids") or []):
            return fallback_recommendation
        return fallback_recommendation

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
        keyword_profile = self._build_keyword_profile(
            context,
            metadata={"target_concepts": list(context.get("target_concepts") or [])},
        )
        strict_keywords = keyword_profile["strict"]
        broad_keywords = keyword_profile["broad"]
        selected_types = [
            question_type
            for question_type in (question_types or ["multiple_choice"])
            if question_type == "multiple_choice"
        ] or ["multiple_choice"]

        chunk_text_by_id = {
            str(chunk["_id"]): str(chunk.get("content") or "") for chunk in chunks
        }
        candidates = self.question_fallback_service.build_candidates(
            lesson_title=lesson_title,
            lesson_summary=str(context["lesson"].get("summary") or ""),
            chunks=chunks,
            target_count=target_count,
            question_types=selected_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
            retry_attempts=1 if relaxed_mode else 0,
            target_concepts=context.get("target_concepts") or [],
        )
        validation = self.question_validation_service.validate_candidates(
            candidates=candidates,
            allowed_chunk_ids=list(chunk_text_by_id.keys()),
            chunk_text_by_id=chunk_text_by_id,
            default_difficulty=difficulty,
            default_bloom_levels=bloom_levels or ["understand"],
        )
        questions: List[ValidatedLessonQuestion] = []
        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks if chunk.get("_id")}
        for question in validation.questions:
            excerpt = str(question.metadata.get("source_excerpt") or "").strip()
            excerpt_score = self._score_excerpt_for_fallback(
                excerpt=excerpt,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if not relaxed_mode and float(excerpt_score) < 1.25:
                continue
            metadata = dict(question.metadata)
            metadata["fallback_excerpt_score"] = round(float(excerpt_score), 4)
            metadata["reasoning_note"] = (
                "Generated by deterministic local fallback from recommended chunk."
            )
            metadata["generation_mode"] = "local_fallback"
            metadata["generation_source"] = "local_fallback"
            questions.append(
                ValidatedLessonQuestion(
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
            )
            if len(questions) >= target_count:
                break
        required_target_concepts = self._extract_target_concepts(
            {"target_concepts": list(context.get("target_concepts") or [])}
        )
        coverage_report = (
            self.compute_concept_coverage_rate(
                questions,
                valid_target_concepts=required_target_concepts,
                chunk_map=chunk_map,
            )
            if required_target_concepts
            else {"missing_concepts": []}
        )
        missing_concepts = list(coverage_report.get("missing_concepts", []))
        if missing_concepts or len(questions) < target_count:
            reinforcement_context = {
                **context,
                "target_concepts": list(
                    missing_concepts
                    or required_target_concepts
                    or context.get("target_concepts")
                    or []
                ),
            }
            reinforcement_chunks = self._filter_chunks_for_required_concepts(
                chunks=chunks,
                required_concepts=missing_concepts,
            )
            reinforcement_questions = self._build_reinforcement_questions(
                context=reinforcement_context,
                chunks=reinforcement_chunks or chunks,
                target_count=max(target_count - len(questions), len(missing_concepts)),
                difficulty=difficulty,
                bloom_levels=bloom_levels or ["understand", "apply"],
            )
            if reinforcement_questions:
                questions = self._prioritize_local_fallback_question_pool(
                    questions=[*questions, *reinforcement_questions],
                    target_count=max(target_count, len(questions) + len(missing_concepts)),
                    required_concepts=required_target_concepts,
                    chunk_map=chunk_map,
                )
        return questions[: max(target_count, len(required_target_concepts or []))]

    def _filter_chunks_for_required_concepts(
        self,
        *,
        chunks: List[Dict[str, Any]],
        required_concepts: Sequence[str],
    ) -> List[Dict[str, Any]]:
        normalized_required = lesson_assessment_sizing_service._normalize_concepts(
            required_concepts or []
        )
        if not normalized_required:
            return list(chunks)
        filtered: List[Dict[str, Any]] = []
        for chunk in chunks:
            chunk_concepts = lesson_assessment_sizing_service._normalize_concepts(
                chunk.get("covered_concepts")
                or (
                    (chunk.get("metadata") or {}).get("covered_concepts")
                    if isinstance(chunk.get("metadata"), dict)
                    else []
                )
                or []
            )
            if set(chunk_concepts).intersection(set(normalized_required)):
                filtered.append(chunk)
        return filtered

    def _prioritize_local_fallback_question_pool(
        self,
        *,
        questions: Sequence[ValidatedLessonQuestion],
        target_count: int,
        required_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> List[ValidatedLessonQuestion]:
        if target_count <= 0:
            return []

        deduped: List[ValidatedLessonQuestion] = []
        seen_signatures: set[str] = set()
        for question in questions:
            signature = self._question_signature(question)
            if not signature or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(question)
        if not deduped:
            return []

        ranked_questions = sorted(
            deduped,
            key=lambda item: self._rank_local_fallback_question(item),
            reverse=True,
        )
        normalized_required = lesson_assessment_sizing_service._normalize_concepts(
            required_concepts or []
        )
        if not normalized_required:
            return ranked_questions[:target_count]

        prioritized: List[ValidatedLessonQuestion] = []
        used_signatures: set[str] = set()
        for concept in normalized_required:
            matched_question = next(
                (
                    item
                    for item in ranked_questions
                    if self._question_signature(item) not in used_signatures
                    and self._question_covers_canonical_concept(
                        question=item,
                        concept=concept,
                        chunk_map=chunk_map,
                    )
                ),
                None,
            )
            if matched_question is None:
                continue
            signature = self._question_signature(matched_question)
            if not signature:
                continue
            used_signatures.add(signature)
            prioritized.append(matched_question)

        for item in ranked_questions:
            if len(prioritized) >= target_count:
                break
            signature = self._question_signature(item)
            if not signature or signature in used_signatures:
                continue
            used_signatures.add(signature)
            prioritized.append(item)
        return prioritized[:target_count]

    def _rank_local_fallback_question(
        self, question: ValidatedLessonQuestion
    ) -> float:
        metadata = question.metadata or {}
        score = float(metadata.get("fallback_excerpt_score", 0.0) or 0.0)
        score += float(metadata.get("fallback_priority_score", 0.0) or 0.0)
        score += float(len(metadata.get("matched_target_concepts") or [])) * 1.15
        if bool(metadata.get("target_concept_match")):
            score += 1.35
        generation_mode = str(metadata.get("generation_mode") or "").strip().lower()
        if generation_mode == "local_fill":
            score += 0.2
        elif generation_mode == "local_fallback":
            score += 0.15
        if question.question_type == "multiple_choice":
            score += 0.2
        if question.bloom_level in {"apply", "analyze"}:
            score += 0.1
        return score

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
        keyword_profile = self._build_keyword_profile(
            context,
            metadata={"target_concepts": list(context.get("target_concepts") or [])},
        )
        strict_keywords = keyword_profile["strict"]
        broad_keywords = keyword_profile["broad"]
        selected_bloom_levels = bloom_levels or ["understand"]
        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks if chunk.get("_id")}
        required_target_concepts = self._extract_target_concepts(
            {"target_concepts": list(context.get("target_concepts") or [])}
        )

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
        focus_usage: Dict[str, int] = {}
        max_per_focus = 2 if target_count >= 5 else 1
        for index, (_, chunk, excerpt) in enumerate(chunk_candidates):
            if len(questions) >= target_count:
                break

            excerpt_norm = self._normalize_text(excerpt)
            focus = self._resolve_reinforcement_focus(
                chunk=chunk,
                excerpt=excerpt_norm,
                strict_keywords=strict_keywords,
                broad_keywords=broad_keywords,
            )
            if not focus:
                continue
            normalized_focus = self._normalize_term_key(focus)
            if focus_usage.get(normalized_focus, 0) >= max_per_focus:
                continue

            question_type = "multiple_choice"
            bloom_level = selected_bloom_levels[index % len(selected_bloom_levels)]

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
            question_text = self._build_reinforcement_mc_prompt(
                lesson_title=lesson_title,
                instruction_role=str(chunk.get("instruction_role") or "explanation"),
                index=index,
            )
            correct_answer = focus
            distractors = distractors[:3]
            explanation = (
                f"Đoạn trích có nhắc trực tiếp '{focus}', vì vậy đây là đáp án phù hợp nhất trong các lựa chọn."
            )

            chunk_concepts = lesson_assessment_sizing_service._normalize_concepts(
                chunk.get("covered_concepts")
                or (
                    (chunk.get("metadata") or {}).get("covered_concepts")
                    if isinstance(chunk.get("metadata"), dict)
                    else []
                )
                or []
            )
            question_metadata = {
                "source_excerpt": excerpt,
                "question_focus": focus,
                "concept_focus": focus,
                "instruction_role": str(chunk.get("instruction_role") or "explanation"),
                "covered_concepts": chunk_concepts,
                "target_concepts": list(required_target_concepts),
                "fallback_excerpt_score": round(float(_), 4),
                "reasoning_note": "Generated by medium-quality reinforcement fill from lesson chunk.",
                "generation_mode": "local_fill",
                "generation_source": "local_fill",
            }
            question_item = ValidatedLessonQuestion(
                question_type=question_type,
                question=question_text,
                correct_answer=correct_answer,
                distractors=distractors,
                explanation=explanation,
                difficulty=difficulty,
                bloom_level=bloom_level,
                chunk_ids=[str(chunk["_id"])],
                metadata=question_metadata,
            )
            matched_targets = self._resolve_matched_target_concepts(
                question=question_item,
                target_concepts=required_target_concepts,
                chunk_map=chunk_map,
            )
            question_item.metadata["matched_target_concepts"] = matched_targets
            question_item.metadata["target_concept_match"] = bool(matched_targets)
            questions.append(
                question_item
            )
            focus_usage[normalized_focus] = focus_usage.get(normalized_focus, 0) + 1

        return questions

    def _resolve_reinforcement_focus(
        self,
        *,
        chunk: Dict[str, Any],
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> str:
        for source in (
            chunk.get("covered_concepts"),
            (chunk.get("metadata") or {}).get("covered_concepts")
            if isinstance(chunk.get("metadata"), dict)
            else [],
        ):
            values = source if isinstance(source, list) else []
            for value in values:
                normalized = self._normalize_text(str(value))
                if (
                    normalized
                    and normalized not in self._FALLBACK_STOP_WORDS
                    and normalized not in self._AMBIGUOUS_TERMS
                ):
                    return str(value).strip()
        return self._find_focus_term(
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        ) or self._find_specific_focus_term(
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )

    @staticmethod
    def _build_reinforcement_mc_prompt(
        *,
        lesson_title: str,
        instruction_role: str,
        index: int,
    ) -> str:
        role = str(instruction_role or "explanation").strip().lower()
        if role == "worked_example":
            return f"Theo vi du trong bai '{lesson_title}', khai niem nao dang duoc minh hoa ro nhat?"
        if role == "summary":
            return f"Theo phan tom tat cua bai '{lesson_title}', khai niem nao la y chinh duoc nhan manh?"
        if role == "introduction":
            return f"Theo phan gioi thieu cua bai '{lesson_title}', khai niem nao duoc dua ra lam trong tam?"
        prompts = [
            f"Theo doan trich cua bai '{lesson_title}', khai niem nao la trong tam noi dung?",
            f"Dua tren doan trich cua bai '{lesson_title}', khai niem nao duoc giai thich truc tiep?",
            f"Theo noi dung bai '{lesson_title}', dap an nao khop nhat voi khai niem da neu trong doan trich?",
        ]
        return prompts[index % len(prompts)]

    def _is_reinforcement_true_false_safe(self, *, statement: str, focus: str) -> bool:
        normalized = self._normalize_text(statement)
        if len(normalized) < 20:
            return False
        if not re.match(r"^[a-z].{18,}$", normalized):
            return False
        if normalized.startswith("example "):
            return False
        if "range(" in normalized or "#" in normalized:
            return False
        if len(statement) > REINFORCEMENT_STATEMENT_MAX_LEN:
            return False
        if statement.count("(") >= 2 or statement.count("[") >= 2 or statement.count("{") >= 1:
            return False
        if normalized.count(":") >= 2:
            return False
        focus_key = self._normalize_text(focus)
        if focus_key and focus_key not in normalized:
            return False
        return True

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
        lesson_summary: str,
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
            lesson_summary=lesson_summary,
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

    def _collect_additional_llm_questions(
        self,
        *,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        existing_questions: List[ValidatedLessonQuestion],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> List[ValidatedLessonQuestion]:
        if not existing_questions or target_count <= len(existing_questions):
            return []

        merged_questions = list(existing_questions)
        used_chunk_ids = {
            chunk_id
            for question in existing_questions
            for chunk_id in question.chunk_ids
            if chunk_id
        }
        attempt = 0
        while (
            len(merged_questions) < target_count
            and attempt < max(1, LLM_FILL_MAX_ATTEMPTS)
        ):
            attempt += 1
            candidate_chunks = [
                chunk
                for chunk in chunks
                if str(chunk.get("_id") or "").strip() not in used_chunk_ids
            ]
            if not candidate_chunks:
                candidate_chunks = list(chunks)
            candidate_chunk_ids = [
                str(chunk.get("_id") or "").strip()
                for chunk in candidate_chunks
                if str(chunk.get("_id") or "").strip()
            ]
            if not candidate_chunk_ids:
                break

            fill_validation = self._run_generation(
                context=context,
                recommendation=recommendation,
                chunks=candidate_chunks,
                chunk_ids=candidate_chunk_ids,
                target_count=max(1, target_count - len(merged_questions)),
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            if not fill_validation or fill_validation.status != "ok":
                break

            merged_validation = self.question_validation_service.merge_deduplicate(
                question_groups=[merged_questions, list(fill_validation.questions)],
                target_count=target_count,
                max_per_chunk=QUESTION_DIVERSITY_MAX_PER_CHUNK,
            )
            if len(merged_validation.questions) <= len(merged_questions):
                break
            merged_questions = list(merged_validation.questions)
            used_chunk_ids = {
                chunk_id
                for question in merged_questions
                for chunk_id in question.chunk_ids
                if chunk_id
            }

        if len(merged_questions) <= len(existing_questions):
            return []
        existing_signatures = {
            self.question_validation_service._signature(question)
            for question in existing_questions
        }
        return [
            question
            for question in merged_questions
            if self.question_validation_service._signature(question)
            not in existing_signatures
        ]

    def _build_existing_or_insufficient_response(
        self,
        *,
        lesson_id: str,
        chunk_ids: List[str],
        default_message: str,
        source_stats: Dict[str, int] | None = None,
        filtered_count: int = 0,
        cache_stats: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        stats = source_stats or {
            "template": 0,
            "llm": 0,
            "local_fallback": 0,
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
            "fallback_used": bool(stats.get("local_fallback", 0)),
            "cache_stats": cache_stats or self._claim_cache_stats_since(None),
            "filtered_count": filtered_count,
            "message": self._build_llm_fallback_message(default_message),
        }

    def _snapshot_claim_cache_stats(self) -> Dict[str, Any]:
        return dict(self.question_template_service.get_claim_cache_stats())

    def _claim_cache_stats_since(
        self, before: Dict[str, Any] | None
    ) -> Dict[str, Any]:
        after = self._snapshot_claim_cache_stats()
        baseline = before or {}
        hits = max(
            0,
            int(after.get("hits", 0) or 0) - int(baseline.get("hits", 0) or 0),
        )
        misses = max(
            0,
            int(after.get("misses", 0) or 0) - int(baseline.get("misses", 0) or 0),
        )
        stores = max(
            0,
            int(after.get("stores", 0) or 0) - int(baseline.get("stores", 0) or 0),
        )
        requests = hits + misses
        return {
            "scope": "shared_template_claim_cache",
            "entries": int(after.get("entries", 0) or 0),
            "hits": hits,
            "misses": misses,
            "stores": stores,
            "requests": requests,
            "request_hit_rate": round(hits / max(requests, 1), 4),
            "lifetime_hit_rate": float(after.get("hit_rate", 0.0) or 0.0),
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
    def _build_keyword_profile(
        cls,
        context: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, List[str]]:
        metadata = metadata or {}
        target_concepts: List[str] = []
        for source in (
            metadata.get("target_concepts"),
            metadata.get("current_focus_concepts"),
            context.get("target_concepts"),
        ):
            values = source if isinstance(source, list) else [source] if source else []
            for item in values:
                token = str(item).strip()
                if token and token not in target_concepts:
                    target_concepts.append(token)
        strict_sources = [
            str(context["lesson"].get("title") or ""),
            *[str(item) for item in context["lesson"].get("keywords", [])],
            *target_concepts,
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
    def _extract_target_concepts(
        cls,
        metadata: Dict[str, Any] | None,
    ) -> List[str]:
        metadata = metadata or {}
        normalized: List[str] = []
        seen: set[str] = set()
        for source in (
            metadata.get("target_concepts"),
            metadata.get("required_concepts"),
            metadata.get("current_focus_concepts"),
        ):
            values = source if isinstance(source, list) else [source] if source else []
            for item in values:
                token = cls._normalize_text(str(item))
                if not token or token in seen:
                    continue
                seen.add(token)
                normalized.append(token)
        return normalized

    @classmethod
    def _concept_token_set(cls, value: str) -> set[str]:
        normalized = cls._normalize_text(value)
        if not normalized:
            return set()
        tokens = {normalized}
        for token in normalized.split():
            singular = concept_normalization_service._singularize(token)
            if len(singular) >= 3 and singular not in cls._FALLBACK_STOP_WORDS:
                tokens.add(singular)
        return tokens

    @classmethod
    def _candidate_matches_concept(cls, candidate: str, target: str) -> bool:
        normalized_candidate = cls._normalize_text(candidate)
        normalized_target = cls._normalize_text(target)
        if not normalized_candidate or not normalized_target:
            return False
        if (
            normalized_target in normalized_candidate
            or normalized_candidate in normalized_target
            or concept_normalization_service._match_canonical_concept(
                normalized_target,
                [normalized_candidate],
            )
            is not None
        ):
            return True

        candidate_tokens = cls._concept_token_set(normalized_candidate)
        target_tokens = cls._concept_token_set(normalized_target)
        if not candidate_tokens or not target_tokens:
            return False
        overlap = candidate_tokens.intersection(target_tokens)
        if overlap:
            return True
        return bool(
            {
                token
                for token in candidate_tokens
                if any(token in target_token or target_token in token for target_token in target_tokens)
            }
        )

    def _collect_question_concept_candidates(
        self,
        *,
        question: ValidatedLessonQuestion,
        chunk_map: Dict[str, Dict[str, Any]],
        include_chunk_content: bool = False,
    ) -> List[str]:
        candidate_texts: List[str] = [
            str((question.metadata or {}).get("concept_focus") or ""),
            str((question.metadata or {}).get("question_focus") or ""),
            str((question.metadata or {}).get("source_excerpt") or ""),
            str(question.correct_answer or ""),
            str(question.question or ""),
        ]
        for key in ("covered_concepts", "target_concepts", "matched_target_concepts"):
            for value in (question.metadata or {}).get(key) or []:
                candidate_texts.append(str(value))
        for chunk_id in question.chunk_ids:
            chunk = chunk_map.get(chunk_id) or {}
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            for source in (
                chunk.get("covered_concepts"),
                chunk.get("matched_required_concepts"),
                metadata.get("covered_concepts"),
                metadata.get("matched_required_concepts"),
            ):
                values = source if isinstance(source, list) else [source] if source else []
                for value in values:
                    candidate_texts.append(str(value))
            if include_chunk_content:
                candidate_texts.append(str(chunk.get("content") or ""))
        return [
            self._normalize_text(value)
            for value in candidate_texts
            if self._normalize_text(value)
        ]

    def _resolve_matched_target_concepts(
        self,
        *,
        question: ValidatedLessonQuestion,
        target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        return resolve_target_matches(
            service=self,
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )

    def _question_matches_target_concepts(
        self,
        *,
        question: ValidatedLessonQuestion,
        target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> bool:
        return question_matches_targets(
            service=self,
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )

    @classmethod
    def _collect_keywords(cls, sources: List[str], *, strict_mode: bool) -> List[str]:
        return collect_target_keywords(
            service_cls=cls,
            sources=sources,
            strict_mode=strict_mode,
        )

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
        if normalized in {"class", "classes"}:
            return "class"
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
    def _resolve_matched_target_concepts(
        self,
        *,
        question: ValidatedLessonQuestion,
        target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        return resolve_target_matches(
            service=self,
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )

    def _question_matches_target_concepts(
        self,
        *,
        question: ValidatedLessonQuestion,
        target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> bool:
        return question_matches_targets(
            service=self,
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )

    @classmethod
    def _collect_keywords(cls, sources: List[str], *, strict_mode: bool) -> List[str]:
        return collect_target_keywords(
            service_cls=cls,
            sources=sources,
            strict_mode=strict_mode,
        )

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
        return fallback_build_question(
            service=self,
            question_type=question_type,
            lesson_title=lesson_title,
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
            relaxed_mode=relaxed_mode,
        )

    def _build_distractors(
        self,
        *,
        answer: str,
        excerpt: str,
        keywords: List[str],
        category: str,
        relaxed_mode: bool,
    ) -> List[str]:
        return fallback_build_distractors(
            service=self,
            answer=answer,
            excerpt=excerpt,
            keywords=keywords,
            category=category,
            relaxed_mode=relaxed_mode,
        )

    def _find_specific_focus_term(
        self,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> str:
        return fallback_find_specific_focus_term(
            service=self,
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )

    def _extract_contextual_terms(
        self,
        *,
        excerpt: str,
        keywords: List[str],
        category: str,
        limit: int,
    ) -> List[str]:
        return fallback_extract_contextual_terms(
            service=self,
            excerpt=excerpt,
            keywords=keywords,
            category=category,
            limit=limit,
        )

    @classmethod
    def _find_focus_term(
        cls,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> str:
        return fallback_find_focus_term(
            service_cls=cls,
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )

    @classmethod
    def _has_context_anchor(cls, *, excerpt: str, focus_term: str) -> bool:
        return fallback_has_context_anchor(
            service_cls=cls,
            excerpt=excerpt,
            focus_term=focus_term,
        )

    @classmethod
    def _score_excerpt_for_fallback(
        cls,
        *,
        excerpt: str,
        strict_keywords: List[str],
        broad_keywords: List[str],
    ) -> float:
        return fallback_score_excerpt(
            service_cls=cls,
            excerpt=excerpt,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )

    @classmethod
    def _classify_term(cls, term: str) -> str:
        return fallback_classify_term(service_cls=cls, term=term)

    @staticmethod
    def _build_multiple_choice_prompt(
        *, lesson_title: str, category: str, focus_term: str
    ) -> str:
        return build_mc_prompt(
            lesson_title=lesson_title,
            category=category,
            focus_term=focus_term,
        )

    @staticmethod
    def _build_short_answer_prompt(*, lesson_title: str, focus_term: str) -> str:
        return build_sa_prompt(lesson_title=lesson_title, focus_term=focus_term)

    @staticmethod
    def _summarize_excerpt(*, excerpt: str, focus_term: str) -> str:
        return summarize_excerpt_text(
            service_cls=LessonScopedQuestionGenerationService,
            excerpt=excerpt,
            focus_term=focus_term,
        )

    @staticmethod
    def _clean_true_false_statement(statement: str) -> str:
        return clean_tf_statement(statement)

    def _load_generation_scope(
        self,
        *,
        lesson_id: str,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        return load_question_generation_scope(
            self,
            lesson_id=lesson_id,
            context=context,
            recommendation=recommendation,
        )

    def _question_signature(self, question: ValidatedLessonQuestion) -> str:
        return build_question_signature(self, question)

    def _question_signature_from_parts(
        self, *, question_text: Any, correct_answer: Any
    ) -> str:
        return build_question_signature_from_parts(
            self,
            question_text=question_text,
            correct_answer=correct_answer,
        )

    def _collect_excluded_question_signatures(
        self,
        *,
        existing_questions: Sequence[Dict[str, Any]] | None,
        generation_metadata: Dict[str, Any] | None,
    ) -> set[str]:
        return collect_excluded_signatures(
            self,
            existing_questions=existing_questions,
            generation_metadata=generation_metadata,
        )

    def _build_template_validation(
        self,
        *,
        lesson_title: str,
        lesson_summary: str,
        chunks: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        chunk_ids: List[str],
        chunk_text_by_id: Dict[str, str],
    ):
        return build_template_fill_validation(
            self,
            lesson_title=lesson_title,
            lesson_summary=lesson_summary,
            chunks=chunks,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
            chunk_ids=chunk_ids,
            chunk_text_by_id=chunk_text_by_id,
            max_per_chunk=QUESTION_DIVERSITY_MAX_PER_CHUNK,
        )

    def _collect_additional_llm_questions(
        self,
        *,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        existing_questions: List[ValidatedLessonQuestion],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
    ) -> List[ValidatedLessonQuestion]:
        return collect_llm_fill_questions(
            self,
            context=context,
            recommendation=recommendation,
            chunks=chunks,
            chunk_ids=chunk_ids,
            existing_questions=existing_questions,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
            max_attempts=LLM_FILL_MAX_ATTEMPTS,
        )


lesson_question_generation_service = LessonScopedQuestionGenerationService()
