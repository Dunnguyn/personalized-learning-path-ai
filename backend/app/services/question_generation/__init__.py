"""
Question generation feature package.

This package groups together the rule-based generator, grounded LLM pipeline,
and supporting NLP/template utilities for lesson question generation.
"""

from .generator import (
    LessonConcept,
    QuestionGenerator,
    debug_lesson_question_generation,
    generate_questions,
    generate_questions_for_lesson,
)
from .llm_generator import GeneratedLessonQuestion, LessonLLMQuestionGenerator
from .pipeline import LessonQuestionGenerationPipeline, generate_lesson_questions_with_llm
from .rules import detect_concept_type, extract_keywords, normalize_concept
from .templates import select_template

__all__ = [
    "GeneratedLessonQuestion",
    "LessonConcept",
    "LessonLLMQuestionGenerator",
    "LessonQuestionGenerationPipeline",
    "QuestionGenerator",
    "debug_lesson_question_generation",
    "detect_concept_type",
    "extract_keywords",
    "generate_lesson_questions_with_llm",
    "generate_questions",
    "generate_questions_for_lesson",
    "normalize_concept",
    "select_template",
]
