"""
Learning path feature package.

This package contains the personalized learning path generation flow and
supporting helpers for curriculum assembly and resource recommendation within
the learning path flow.
"""

__all__ = [
    "filter_resources_by_bloom",
    "filter_resources_by_source",
    "generate_learning_path",
    "get_concept_resource_stats",
    "recommend_resources_for_concept",
    "recommend_resources_for_concepts",
]


def __getattr__(name):
    if name == "generate_learning_path":
        from .service import generate_learning_path

        exports = {
            "generate_learning_path": generate_learning_path,
        }
        return exports[name]

    if name in {
        "filter_resources_by_bloom",
        "filter_resources_by_source",
        "get_concept_resource_stats",
        "recommend_resources_for_concept",
        "recommend_resources_for_concepts",
    }:
        from .recommender import (
            filter_resources_by_bloom,
            filter_resources_by_source,
            get_concept_resource_stats,
            recommend_resources_for_concept,
            recommend_resources_for_concepts,
        )

        exports = {
            "filter_resources_by_bloom": filter_resources_by_bloom,
            "filter_resources_by_source": filter_resources_by_source,
            "get_concept_resource_stats": get_concept_resource_stats,
            "recommend_resources_for_concept": recommend_resources_for_concept,
            "recommend_resources_for_concepts": recommend_resources_for_concepts,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
