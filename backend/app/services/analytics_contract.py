"""Shared contracts for canonical analytics and event logging."""

from __future__ import annotations

from typing import Dict, Iterable, List, Set

EVENT_NAME_EQUIVALENTS: Dict[str, Set[str]] = {
    "lesson_opened": {"lesson_opened", "lesson_started"},
    "lesson_completed": {"lesson_completed", "complete_lesson"},
    "resource_viewed": {"resource_viewed", "resource_opened"},
    "resource_completed": {"resource_completed", "resource_finished"},
    "retry_requested": {"retry_requested", "lesson_retried"},
    "quiz_submitted": {"quiz_submitted"},
    "recommendation_shown": {"recommendation_shown"},
    "recommendation_clicked": {"recommendation_clicked"},
    "recommendation_feedback": {"recommendation_feedback"},
    "resource_clicked": {"resource_clicked"},
    "learning_path_generated": {"learning_path_generated"},
    "api_called": {"api_called"},
    "api_failed": {"api_failed"},
    "llm_called": {"llm_called"},
    "mastery_updated": {"mastery_updated"},
    "confidence_updated": {"confidence_updated"},
    "analytics_dashboard_viewed": {"analytics_dashboard_viewed"},
}

COMMON_EVENT_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_type",
    "event_name",
    "schema_version",
    "timestamp",
    "user_id",
    "session_id",
    "subject_id",
    "path_id",
    "chapter_id",
    "lesson_id",
    "concept_id",
    "concept_ids",
    "resource_id",
    "question_id",
    "attempt_id",
    "duration_ms",
    "score",
    "accuracy",
    "question_count",
    "total_questions",
    "mastery_before",
    "mastery_after",
    "confidence_before",
    "confidence_after",
    "recommendation_score",
    "rank_position",
    "llm_model",
    "token_input",
    "token_output",
    "cost_estimate",
    "latency_ms",
    "success",
    "error_code",
    "metadata",
)

HOISTED_METADATA_FIELDS: tuple[str, ...] = (
    "session_id",
    "question_id",
    "attempt_id",
    "score",
    "accuracy",
    "question_count",
    "total_questions",
)

DOMAIN_SOURCE_OF_TRUTH: Dict[str, Dict[str, str]] = {
    "user_profile": {
        "api": "/api/learner-profile/me",
        "service": "LearnerProfileService",
        "collection": "learner_profiles",
        "legacy": "users.level + users.learning_goal are mirrors only",
    },
    "learning_path": {
        "api": "/api/learning-paths/*",
        "service": "UnifiedLearningPathService",
        "collection": "learning_paths",
        "legacy": "HybridLearningPathService is implementation base, not the owning domain boundary",
    },
    "progress": {
        "api": "/api/progress/*",
        "service": "progress_tracking.progress",
        "collection": "progress",
        "legacy": "knowledge tracing enriches progress but does not own the canonical record",
    },
    "attempts": {
        "api": "/api/learning-paths/lesson-progress + adaptive quiz flows",
        "service": "AdaptiveAttemptRepository",
        "collection": "lesson_quiz_attempts",
        "legacy": "exercise_attempts remains backward-compatible history",
    },
    "learner_state": {
        "api": "/api/adaptive/state/*",
        "service": "LearnerStateService",
        "collection": "learner_state_snapshots",
        "legacy": "user_learning_state is adaptive working state, not reporting source-of-truth",
    },
    "recommendations": {
        "api": "/api/recommendations/*",
        "service": "HybridRecommendationService",
        "collection": "event_logs + lesson_recommended_chunks",
        "legacy": "recommendation interactions are analyzed from canonical events",
    },
}


def canonical_event_name(event_name: str) -> str:
    normalized = str(event_name or "").strip().lower()
    if not normalized:
        return ""
    for canonical, aliases in EVENT_NAME_EQUIVALENTS.items():
        if normalized in aliases:
            return canonical
    return normalized


def equivalent_event_names(*canonical_names: str) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()
    for name in canonical_names:
        canonical = canonical_event_name(name)
        variants = EVENT_NAME_EQUIVALENTS.get(canonical, {canonical} if canonical else set())
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                names.append(variant)
    return names


def is_equivalent_event(event_name: str, *canonical_names: str) -> bool:
    normalized = canonical_event_name(event_name)
    return any(normalized == canonical_event_name(name) for name in canonical_names)


def analytics_metadata() -> Dict[str, Dict[str, str]]:
    return {key: dict(value) for key, value in DOMAIN_SOURCE_OF_TRUTH.items()}
