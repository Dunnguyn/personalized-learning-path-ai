"""Recommendation filtering helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from backend.app.services.recommendation.normalization import (
    build_concept_match_context_from_terms,
    extract_resource_keys,
)


def _aliases(resource: Dict[str, Any]) -> set[str]:
    return extract_resource_keys(resource)


def _intersects(resource: Dict[str, Any], keys: set[str]) -> bool:
    return bool(_aliases(resource) & keys)


def apply_hard_filters(
    service: Any,
    *,
    resources: Sequence[Dict[str, Any]],
    user_id: str | int,
    mode: str,
    learner_level: str,
    lesson_context: Dict[str, Any] | None,
    focus_concepts: Sequence[str],
    query_tokens: Sequence[str],
    chunk_signal_map: Dict[str, Dict[str, Any]] | None,
    limit: int,
) -> List[Dict[str, Any]]:
    completed_resource_ids = set(service.repository.get_recently_completed_resources(user_id))
    recently_seen_resource_ids = set(
        service.repository.get_recently_seen_resources(user_id, limit=40)
    )
    feedback_signals = service.repository.get_recent_resource_feedback(user_id)
    negative_feedback_ids = {
        key for key, signal in feedback_signals.items() if signal.get("negative")
    }
    lesson_context = lesson_context or {}
    lesson_resource_ids = {
        str(item) for item in lesson_context.get("resource_ids", []) if str(item).strip()
    }
    unfinished_lesson_resource_ids = lesson_resource_ids.intersection(
        recently_seen_resource_ids - completed_resource_ids
    )
    lesson_terms = [
        str(lesson_context.get("topic") or "").lower(),
        *[str(item).lower() for item in lesson_context.get("keywords", []) if item],
        *[
            str(item).lower()
            for item in lesson_context.get("learning_objectives", [])
            if item
        ],
    ]
    focus_terms = [str(item).lower() for item in focus_concepts if str(item).strip()]

    base: List[Dict[str, Any]] = []
    dropped_reasons: Dict[str, int] = {}
    for resource in resources:
        if _intersects(resource, completed_resource_ids):
            dropped_reasons["recently_completed"] = dropped_reasons.get("recently_completed", 0) + 1
            continue
        if _intersects(resource, negative_feedback_ids):
            dropped_reasons["recent_negative_feedback"] = dropped_reasons.get("recent_negative_feedback", 0) + 1
            continue
        if service._level_distance(
            learner_level, str(resource.get("level") or learner_level)
        ) > 1:
            dropped_reasons["level_mismatch"] = dropped_reasons.get("level_mismatch", 0) + 1
            continue
        base.append(resource)

    if not base:
        base = [
            resource
            for resource in resources
            if not _intersects(resource, completed_resource_ids)
            and not _intersects(resource, negative_feedback_ids)
            and service._level_distance(
                learner_level, str(resource.get("level") or learner_level)
            )
            <= 1
        ]

    strict: List[Dict[str, Any]] = []
    relaxed: List[Dict[str, Any]] = []
    semantic_level: List[Dict[str, Any]] = []
    for resource in base:
        resource_key = service.repository.get_resource_key(resource)
        aliases = _aliases(resource)
        lesson_match = bool(lesson_resource_ids and aliases.intersection(lesson_resource_ids))
        focus_match = service._matches_any_term(resource, focus_terms)
        context_match = service._matches_any_term(resource, lesson_terms)
        query_match = service._matches_any_term(resource, query_tokens)
        concept_context = build_concept_match_context_from_terms(
            [*focus_terms, *lesson_terms],
            [service._resource_text(resource)],
        )
        concept_score = float(concept_context.get("concept_match_score") or 0.0)
        chunk_signal = (chunk_signal_map or {}).get(resource_key, {})
        chunk_match = service._safe_float(chunk_signal.get("chunk_match_score"), 0.0)
        chunk_coverage = service._safe_float(
            chunk_signal.get("chunk_coverage_score"), 0.0
        )
        context_or_chunk = (
            lesson_match
            or context_match
            or focus_match
            or query_match
            or concept_score >= 0.34
            or chunk_match >= 0.34
            or chunk_coverage >= 0.16
        )

        if mode == "reinforce_weaknesses" and focus_terms and not (
            focus_match or lesson_match or concept_score >= 0.45 or chunk_match >= 0.52 or chunk_coverage >= 0.22
        ):
            if context_or_chunk:
                relaxed.append(resource)
            continue
        if mode == "continue_learning" and lesson_resource_ids and not (
            lesson_match or context_match or concept_score >= 0.40 or chunk_match >= 0.5 or chunk_coverage >= 0.2
        ):
            if context_or_chunk:
                relaxed.append(resource)
            continue
        if context_or_chunk:
            relaxed.append(resource)
        if query_match or concept_score >= 0.25 or chunk_match >= 0.25:
            semantic_level.append(resource)
        strict.append(resource)

    minimum = max(min(limit, 3), 2)
    if len(strict) >= minimum:
        filtered = strict
        stage_used = "strict_lesson_concept_chunk"
        relaxed_reason = None
    elif len(relaxed) >= minimum:
        filtered = relaxed
        stage_used = "relaxed_concept_chunk"
        relaxed_reason = "strict_filter_too_sparse"
    elif len(semantic_level) >= minimum:
        filtered = semantic_level
        stage_used = "semantic_level_match"
        relaxed_reason = "relaxed_filter_too_sparse"
    else:
        filtered = base
        stage_used = "safe_subject_level_fallback"
        relaxed_reason = "semantic_filter_too_sparse"
    service._last_filter_debug = {
        "filter_stage_used": stage_used,
        "filter_relaxed_reason": relaxed_reason,
        "candidate_count_by_stage": {
            "input": len(resources),
            "base": len(base),
            "strict": len(strict),
            "relaxed": len(relaxed),
            "semantic_level": len(semantic_level),
            "selected": len(filtered),
        },
        "dropped_reasons": dropped_reasons,
        "recent_negative_feedback": len(negative_feedback_ids),
        "recently_completed": len(completed_resource_ids),
        "recently_seen": len(recently_seen_resource_ids),
    }
    return sorted(
        filtered,
        key=lambda resource: (
            bool(_aliases(resource) & unfinished_lesson_resource_ids),
            bool(_aliases(resource) & lesson_resource_ids),
            service._safe_float(
                (chunk_signal_map or {})
                .get(service.repository.get_resource_key(resource), {})
                .get("chunk_match_score"),
                0.0,
            ),
            service._safe_float(
                (chunk_signal_map or {})
                .get(service.repository.get_resource_key(resource), {})
                .get("chunk_coverage_score"),
                0.0,
            ),
            service._matches_any_term(resource, focus_terms),
            service._matches_any_term(resource, lesson_terms),
            service._matches_any_term(resource, query_tokens),
        ),
        reverse=True,
    )
