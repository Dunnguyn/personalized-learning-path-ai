from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Sequence

from backend.app.services.question_generation.lesson_content import (
    LessonChunk,
    LessonContentRetrievalService,
)
from backend.app.services.question_generation.llm_generator import (
    GeneratedLessonQuestion,
    LessonLLMQuestionGenerator,
)
from backend.app.services.question_generation.validator import (
    LessonQuestionValidationResult,
    LessonQuestionValidator,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LessonQuestionPipelineResult:
    questions: List[Dict]
    retrieved_chunks: List[LessonChunk]
    validation: LessonQuestionValidationResult
    llm_used: bool


class LessonQuestionGenerationPipeline:
    """
    End-to-end MVP pipeline:
    1. retrieve lesson chunks
    2. prompt builder
    3. LLM question generation
    4. validation
    5. return normalized question dicts
    """

    def __init__(self) -> None:
        self.retrieval_service = LessonContentRetrievalService()
        self.generator = LessonLLMQuestionGenerator()
        self.validator = LessonQuestionValidator()

    def run(
        self,
        *,
        lesson_id: str,
        lesson_title: str,
        concepts: Sequence[str],
        target_count: int,
    ) -> LessonQuestionPipelineResult:
        chunks = self.retrieval_service.get_relevant_chunks(lesson_id=lesson_id)
        llm_questions: List[GeneratedLessonQuestion] = self.generator.generate(
            lesson_id=lesson_id,
            lesson_title=lesson_title,
            concepts=concepts,
            chunks=chunks,
            target_count=target_count * 2,
        )
        validation = self.validator.validate(
            questions=llm_questions,
            chunks=chunks,
            target_count=target_count,
        )
        normalized = [self._to_question_payload(item) for item in validation.valid_questions]
        return LessonQuestionPipelineResult(
            questions=normalized,
            retrieved_chunks=chunks,
            validation=validation,
            llm_used=self.generator.is_available(),
        )

    @staticmethod
    def _to_question_payload(item: GeneratedLessonQuestion) -> Dict:
        return {
            "question": item.question,
            "options": item.options,
            "correct_option": item.correct_option,
            "answer": item.answer,
            "explanation": item.explanation,
            "keywords": item.keywords,
            "difficulty": item.difficulty,
            "concept": item.concept,
            "source_excerpt": item.source_excerpt,
            "source_chunk_id": item.source_chunk_id,
            "relation_type": "grounded_llm",
            "bloom_level": "understand",
            "template_id": "llm_grounded_v1",
            "related_concepts": [],
        }


def generate_lesson_questions_with_llm(
    lesson_id: str,
    lesson_title: str,
    concepts: Sequence[str],
    target_count: int,
) -> LessonQuestionPipelineResult:
    pipeline = LessonQuestionGenerationPipeline()
    return pipeline.run(
        lesson_id=lesson_id,
        lesson_title=lesson_title,
        concepts=concepts,
        target_count=target_count,
    )
