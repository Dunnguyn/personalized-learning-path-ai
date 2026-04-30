"""Backward-compatible import shim for lesson question generation."""

from backend.app.services.question_generation.orchestrator import (
    LessonScopedQuestionGenerationService,
    lesson_question_generation_service,
)

__all__ = [
    "LessonScopedQuestionGenerationService",
    "lesson_question_generation_service",
]
