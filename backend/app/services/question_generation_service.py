"""Lesson-scoped question generation and question bank storage."""

from __future__ import annotations

import re
from typing import Any, Dict, List
import unicodedata

from backend.app.ai_module import LessonQuestionLLMClient
from backend.app.repositories import (
    LessonRecommendedChunkRepository,
    LessonRepository,
    QuestionBankRepository,
    ResourceChunkRepository,
)
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.prompt_builder import LessonQuestionPromptContext, LessonScopedPromptBuilder
from backend.app.services.question_validator import (
    LessonScopedQuestionValidator,
    ValidatedLessonQuestion,
)


class LessonScopedQuestionGenerationService:
    """Generate questions only from already recommended lesson chunks."""

    _CONCEPT_ALIASES = {
        "bien": ["variable", "variables", "assignment", "value"],
        "kieu du lieu": ["data type", "type", "types", "string", "integer", "float", "boolean"],
        "toan tu": ["operator", "operators", "expression", "arithmetic", "comparison", "logical"],
        "list": ["list", "lists", "append", "sort", "index", "slice"],
        "dict": ["dict", "dictionary", "dictionaries", "key", "value", "keys", "values", "items"],
        "dictionary": ["dict", "dictionary", "dictionaries", "key", "value", "keys", "values", "items"],
        "tuple": ["tuple", "tuples", "pair", "pairs"],
        "set": ["set", "sets", "unique"],
        "ham": ["function", "functions", "method", "methods", "def", "return"],
        "vong lap": ["loop", "loops", "while", "for", "iteration", "iterable"],
        "dieu kien": ["condition", "conditional", "if", "elif", "else", "boolean"],
        "chuoi": ["string", "strings", "split", "strip", "text"],
        "tep": ["file", "files", "open", "read", "write"],
        "xu ly du lieu": ["data", "processing", "analysis", "count", "parse", "extract"],
    }
    _STRICT_CONCEPT_ALIASES = {
        "bien": ["variable", "variables", "assignment"],
        "kieu du lieu": ["data type", "type", "types", "string", "integer", "float", "boolean"],
        "toan tu": ["operator", "operators", "expression", "arithmetic", "comparison", "logical"],
        "list": ["list", "lists", "append", "sort", "slice"],
        "dict": ["dict", "dictionary", "dictionaries", "key", "keys", "item", "items"],
        "dictionary": ["dict", "dictionary", "dictionaries", "key", "keys", "item", "items"],
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
        "data_structure": ["list", "dict", "tuple", "set", "dictionary", "keys", "values", "items"],
        "method": ["append", "sort", "items", "keys", "values", "split", "strip", "findall", "open", "read"],
        "data_type": ["string", "integer", "float", "boolean", "value", "variable", "expression"],
        "operator": ["operator", "arithmetic", "comparison", "logical", "expression", "assignment"],
        "general": ["variable", "value", "expression", "function", "loop", "string", "module", "class"],
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

    def __init__(self) -> None:
        self.lesson_structure_service = lesson_structure_service
        self.lesson_chunk_service = lesson_chunk_service
        self.recommendation_repository = LessonRecommendedChunkRepository()
        self.lesson_repository = LessonRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.question_repository = QuestionBankRepository()
        self.prompt_builder = LessonScopedPromptBuilder()
        self.validator = LessonScopedQuestionValidator()
        self.llm_client = LessonQuestionLLMClient()

        self.recommendation_repository.ensure_indexes()
        self.question_repository.ensure_indexes()

    def generate_questions_for_lesson(
        self,
        *,
        lesson_id: str,
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        overwrite: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self.lesson_structure_service.get_lesson_context(lesson_id)
        recommendation = self._resolve_recommendation(lesson_id, context)
        existing_questions = self.question_repository.list_by_lesson(lesson_id)
        existing_count = len(existing_questions)

        recommendation, chunk_ids, chunks = self._load_generation_scope(
            lesson_id=lesson_id,
            context=context,
            recommendation=recommendation,
        )
        validation = self._run_generation(
            context=context,
            chunks=chunks,
            chunk_ids=chunk_ids,
            target_count=target_count,
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
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
                validation = self._run_generation(
                    context=context,
                    chunks=chunks,
                    chunk_ids=chunk_ids,
                    target_count=target_count,
                    question_types=question_types,
                    difficulty=difficulty,
                    bloom_levels=bloom_levels,
                )

        if validation is None:
            return self._build_existing_or_insufficient_response(
                lesson_id=lesson_id,
                chunk_ids=chunk_ids,
                existing_count=existing_count,
                default_message="Không thể nhận phản hồi hợp lệ từ dịch vụ tạo câu hỏi.",
            )
        if validation.status == "insufficient_context":
            return {
                "lesson_id": lesson_id,
                "status": "insufficient_context",
                "generated_count": 0,
                "question_ids": [],
                "chunks_used": chunk_ids,
                "insufficient_data": True,
                "reused_existing": False,
                "existing_count": existing_count,
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
            fallback_questions = self._build_fallback_questions(
                context=context,
                chunks=chunks,
                target_count=target_count,
                question_types=question_types,
                difficulty=difficulty,
                bloom_levels=bloom_levels,
            )
            if not fallback_questions:
                return self._build_existing_or_insufficient_response(
                    lesson_id=lesson_id,
                    chunk_ids=chunk_ids,
                    existing_count=existing_count,
                    default_message="Hệ thống tạm thời chưa tạo được câu hỏi tự động từ nội dung bài học hiện tại.",
                )
            validation_message = validation.message or "LLM output invalid."
            validation = self._build_validation_from_fallback(
                questions=fallback_questions,
                message=self._build_llm_fallback_message(
                    f"Đã dùng chế độ tạo câu hỏi cục bộ vì dịch vụ AI chưa phản hồi đúng định dạng. {validation_message}"
                ),
            )

        if overwrite:
            self.question_repository.delete_by_lesson(lesson_id)

        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        resource_ids = [str(item) for item in recommendation.get("resource_ids", [])]
        documents = []
        for question in validation.questions:
            question_resource_ids = sorted(
                {
                    str(chunk_map[chunk_id]["resource_id"])
                    for chunk_id in question.chunk_ids
                    if chunk_id in chunk_map
                }
            )
            documents.append(
                {
                    "subject_id": context["subject"]["_id"],
                    "chapter_id": context["chapter"]["_id"],
                    "lesson_id": context["lesson"]["_id"],
                    "chunk_ids": [chunk_map[chunk_id]["_id"] for chunk_id in question.chunk_ids if chunk_id in chunk_map],
                    "resource_ids": [
                        chunk_map[chunk_id]["resource_id"] for chunk_id in question.chunk_ids if chunk_id in chunk_map
                    ],
                    "question_type": question.question_type,
                    "question": question.question,
                    "correct_answer": question.correct_answer,
                    "distractors": question.distractors,
                    "explanation": question.explanation,
                    "difficulty": question.difficulty,
                    "bloom_level": question.bloom_level,
                    "is_ai_generated": question.metadata.get("generation_mode") != "local_fallback",
                    "llm_provider": self.llm_client.provider if question.metadata.get("generation_mode") != "local_fallback" else "local_fallback",
                    "llm_model": self.llm_client.model if question.metadata.get("generation_mode") != "local_fallback" else None,
                    "metadata": {
                        **metadata,
                        **question.metadata,
                        "lesson_recommendation_id": str(recommendation["_id"]),
                        "allowed_resource_ids": resource_ids,
                        "resolved_resource_ids": question_resource_ids,
                    },
                }
            )

        inserted_ids = self.question_repository.insert_many(documents)
        return {
            "lesson_id": lesson_id,
            "status": "ok",
            "generated_count": len(inserted_ids),
            "question_ids": inserted_ids,
            "chunks_used": chunk_ids,
            "insufficient_data": False,
            "reused_existing": False,
            "existing_count": existing_count,
            "message": validation.message,
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
                    "resource_ids": [str(item) for item in question.get("resource_ids", [])],
                    "question_type": question.get("question_type"),
                    "question": question.get("question"),
                    "correct_answer": question.get("correct_answer"),
                    "distractors": question.get("distractors", []),
                    "explanation": question.get("explanation"),
                    "difficulty": question.get("difficulty"),
                    "bloom_level": question.get("bloom_level"),
                    "is_ai_generated": bool(question.get("is_ai_generated", True)),
                    "llm_provider": question.get("llm_provider"),
                    "llm_model": question.get("llm_model"),
                    "metadata": question.get("metadata", {}),
                    "created_at": question.get("created_at"),
                }
            )
        return {
            "lesson_id": lesson_id,
            "total": len(serialized),
            "questions": serialized,
        }

    def _resolve_recommendation(self, lesson_id: str, context: Dict[str, Any]) -> Dict[str, Any] | None:
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
        return self.recommendation_repository.upsert_for_lesson(lesson_id, fallback_payload)

    def _load_generation_scope(
        self,
        *,
        lesson_id: str,
        context: Dict[str, Any],
        recommendation: Dict[str, Any] | None,
    ) -> tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        if not recommendation:
            raise ValueError("Lesson has no recommended chunks. Generate recommended chunks first.")

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
        chunk_payload = [
            {
                "chunk_id": str(chunk["_id"]),
                "resource_id": str(chunk["resource_id"]),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "content": str(chunk.get("content") or ""),
            }
            for chunk in chunks
        ]
        chunk_text_by_id = {item["chunk_id"]: item["content"] for item in chunk_payload}
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
        for _ in range(2):
            raw_text = self.llm_client.generate(retry_prompt or prompt)
            validation = self.validator.parse_and_validate(
                raw_text=raw_text,
                allowed_chunk_ids=chunk_ids,
                chunk_text_by_id=chunk_text_by_id,
                target_count=target_count,
            )
            if validation.status in {"ok", "insufficient_context"}:
                break
            retry_prompt = (
                f"{prompt}\n\nPrevious output was invalid for these reasons: {validation.errors}. "
                "Retry and return only valid JSON following the required schema."
            )
        return validation

    def _refresh_recommendation(self, *, lesson_id: str, metadata: Dict[str, Any]) -> Dict[str, Any] | None:
        try:
            refreshed = self.lesson_chunk_service.recommend_chunks(
                lesson_id=lesson_id,
                max_chunks=8,
                selection_strategy="local_semantic_lexical_refresh_v2",
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
        for index, (_, chunk, excerpt) in enumerate(chunk_candidates):
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
            )
            if not question:
                continue
            questions.append(
                ValidatedLessonQuestion(
                    question_type=question_type,
                    question=question["question"],
                    correct_answer=question["correct_answer"],
                    distractors=question["distractors"],
                    explanation=f"Cau hoi duoc tao truc tiep tu doan trich cua bai hoc '{lesson_title}'.",
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    chunk_ids=[str(chunk["_id"])],
                    metadata={
                        "source_excerpt": excerpt,
                        "reasoning_note": "Generated by deterministic local fallback from recommended chunk.",
                        "generation_mode": "local_fallback",
                    },
                )
            )
        return questions

    def _build_validation_from_fallback(
        self,
        *,
        questions: List[ValidatedLessonQuestion],
        message: str,
        status: str = "ok",
    ):
        return type("FallbackValidationPayload", (), {
            "status": status,
            "message": message,
            "questions": questions,
            "errors": [],
        })()

    def _build_existing_or_insufficient_response(
        self,
        *,
        lesson_id: str,
        chunk_ids: List[str],
        existing_count: int,
        default_message: str,
    ) -> Dict[str, Any]:
        if existing_count > 0:
            return {
                "lesson_id": lesson_id,
                "status": "reused_existing",
                "generated_count": 0,
                "question_ids": [],
                "chunks_used": chunk_ids,
                "insufficient_data": False,
                "reused_existing": True,
                "existing_count": existing_count,
                "message": self._build_llm_fallback_message(
                    f"{default_message} Hệ thống đang dùng lại {existing_count} câu hỏi đã tạo trước đó cho bài học này."
                ),
            }
        return {
            "lesson_id": lesson_id,
            "status": "insufficient_context",
            "generated_count": 0,
            "question_ids": [],
            "chunks_used": chunk_ids,
            "insufficient_data": True,
            "reused_existing": False,
            "existing_count": 0,
            "message": self._build_llm_fallback_message(default_message),
        }

    def _build_llm_fallback_message(self, default_message: str) -> str:
        raw_error = (self.llm_client.get_last_error() or "").lower()
        if not raw_error:
            return default_message
        if "resource_exhausted" in raw_error or "quota exceeded" in raw_error or "429" in raw_error:
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
    def _select_excerpt(*, content: str, strict_keywords: List[str], broad_keywords: List[str]) -> str:
        normalized = re.sub(r"\s+", " ", content or "").strip()
        if not normalized:
            return ""
        segments = re.split(r"(?<=[\.\!\?])\s+", normalized)
        scored_segments = []
        for segment in segments:
            if 60 <= len(segment) <= 260:
                score = LessonScopedQuestionGenerationService._score_excerpt_for_fallback(
                    excerpt=segment,
                    strict_keywords=strict_keywords,
                    broad_keywords=broad_keywords,
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
    ) -> Dict[str, Any] | None:
        excerpt_lower = self._normalize_text(excerpt)
        focus_term = self._find_focus_term(
            excerpt=excerpt_lower,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )
        if not focus_term:
            return None
        if focus_term in self._AMBIGUOUS_TERMS and not self._has_context_anchor(excerpt=excerpt_lower, focus_term=focus_term):
            return None
        category = self._classify_term(focus_term)
        if question_type == "multiple_choice":
            answer = focus_term or self._first_meaningful_word(excerpt)
            if not answer:
                return None
            distractors = self._build_distractors(
                answer=answer,
                keywords=strict_keywords or broad_keywords,
                category=category,
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
            }
        if question_type == "true_false":
            statement = self._summarize_excerpt(excerpt=excerpt, focus_term=focus_term)
            return {
                "question": f"Phat bieu sau la dung hay sai theo doan trich cua bai '{lesson_title}'? \"{statement}\"",
                "correct_answer": "True",
                "distractors": ["False"],
            }
        return {
            "question": self._build_short_answer_prompt(
                lesson_title=lesson_title,
                focus_term=focus_term,
            ),
            "correct_answer": self._summarize_excerpt(excerpt=excerpt, focus_term=focus_term),
            "distractors": [],
        }

    def _build_distractors(self, *, answer: str, keywords: List[str], category: str) -> List[str]:
        normalized_answer = answer.strip().lower()
        candidates = list(self._CATEGORY_POOLS.get(category, []))
        candidates.extend(item for item in keywords if item.strip().lower() != normalized_answer)
        candidates.extend(self._FALLBACK_DISTRACTORS)
        unique: List[str] = []
        seen = {normalized_answer}
        for item in candidates:
            cleaned = item.strip()
            key = cleaned.lower()
            if len(cleaned) < 3 or key in seen or key in self._FALLBACK_STOP_WORDS:
                continue
            seen.add(key)
            unique.append(cleaned)
        return unique

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
            anchors = {"dict", "dictionary", "dictionaries", "list", "lists", "tuple", "tuples"}
            return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
        if focus_term in {"type", "types"}:
            anchors = {"variable", "variables", "string", "integer", "float", "boolean"}
            return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
        if focus_term == "data":
            anchors = {"list", "dict", "dictionary", "variable", "operator", "string", "float", "integer"}
            return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
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
        if any(token in normalized for token in ("list", "dict", "dictionary", "variable", "operator", "string", "float", "integer")):
            score += 0.8
        if len(normalized) < 60:
            score -= 0.5
        return score

    @classmethod
    def _classify_term(cls, term: str) -> str:
        normalized = cls._normalize_text(term)
        if normalized in {"list", "dict", "dictionary", "tuple", "set", "keys", "values", "items"}:
            return "data_structure"
        if normalized in {"append", "sort", "split", "strip", "findall", "open", "read", "write"}:
            return "method"
        if normalized in {"string", "integer", "float", "boolean", "variable", "value"}:
            return "data_type"
        if normalized in {"operator", "arithmetic", "comparison", "logical", "expression", "assignment"}:
            return "operator"
        return "general"

    @staticmethod
    def _build_multiple_choice_prompt(*, lesson_title: str, category: str, focus_term: str) -> str:
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
            return f"Dua tren doan trich cua bai '{lesson_title}', hay tom tat vai tro hoac y nghia cua '{focus_term}'."
        return f"Dua tren doan trich cua bai '{lesson_title}', hay neu y chinh cua noi dung nay."

    @staticmethod
    def _summarize_excerpt(*, excerpt: str, focus_term: str) -> str:
        cleaned = re.sub(r"\s+", " ", excerpt or "").strip().strip('"')
        sentences = [item.strip() for item in re.split(r"(?<=[\.\!\?])\s+", cleaned) if item.strip()]
        if focus_term:
            for sentence in sentences:
                if focus_term in LessonScopedQuestionGenerationService._normalize_text(sentence):
                    return sentence[:220].rstrip(" ,;:") + ("..." if len(sentence) > 220 else "")
        if sentences:
            sentence = sentences[0]
            return sentence[:220].rstrip(" ,;:") + ("..." if len(sentence) > 220 else "")
        return cleaned[:220].rstrip(" ,;:") + ("..." if len(cleaned) > 220 else "")


lesson_question_generation_service = LessonScopedQuestionGenerationService()
