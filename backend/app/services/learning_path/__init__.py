"""
Learning path feature package.

This package contains the personalized learning path generation flow and
supporting helpers for curriculum assembly, lesson assessment seeding, and
resource recommendation within the learning path flow.
"""

from .service import calculate_min_correct_required, generate_learning_path, generate_lesson_mcq_questions
from .recommender import (
    filter_resources_by_bloom,
    filter_resources_by_source,
    get_concept_resource_stats,
    recommend_resources_for_concept,
    recommend_resources_for_concepts,
)

__all__ = [
    "calculate_min_correct_required",
    "filter_resources_by_bloom",
    "filter_resources_by_source",
    "generate_learning_path",
    "generate_lesson_mcq_questions",
    "get_concept_resource_stats",
    "recommend_resources_for_concept",
    "recommend_resources_for_concepts",
]
