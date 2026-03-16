"""
Progress tracking feature package.

This package groups learner progress, lesson confidence state, and confidence
scoring helpers used across quizzes, dashboards, and adaptive learning flows.
"""

from .confidence import (
    calculate_confidence_score,
    get_attempt_confidence,
    get_lesson_confidence,
    get_user_confidence_overview,
    record_confidence_event,
    upsert_lesson_confidence_progress,
)
from .confidence_scorer import score_confidence
from .progress import (
    get_concept_progress,
    get_progress,
    get_user_progress_summary,
    reset_concept_progress,
    reset_user_progress,
    update_progress_batch,
    update_progress_with_confidence,
)

__all__ = [
    "calculate_confidence_score",
    "get_attempt_confidence",
    "get_concept_progress",
    "get_lesson_confidence",
    "get_progress",
    "get_user_confidence_overview",
    "get_user_progress_summary",
    "record_confidence_event",
    "reset_concept_progress",
    "reset_user_progress",
    "score_confidence",
    "update_progress_batch",
    "update_progress_with_confidence",
    "upsert_lesson_confidence_progress",
]
