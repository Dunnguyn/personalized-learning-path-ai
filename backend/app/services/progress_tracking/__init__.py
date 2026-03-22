"""
Progress tracking feature package.

This package groups learner progress and confidence scoring helpers used across
dashboards and adaptive learning flows.
"""

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
    "get_concept_progress",
    "get_progress",
    "get_user_progress_summary",
    "reset_concept_progress",
    "reset_user_progress",
    "score_confidence",
    "update_progress_batch",
    "update_progress_with_confidence",
]
