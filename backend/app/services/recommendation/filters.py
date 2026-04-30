"""Recommendation filtering helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


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
    for resource in resources:
        resource_key = service.repository.get_resource_key(resource)
        if resource_key in completed_resource_ids:
            continue
        if service._level_distance(
            learner_level, str(resource.get("level") or learner_level)
        ) > 1:
            continue
        base.append(resource)

    if not base:
        base = [
            resource
            for resource in resources
            if service.repository.get_resource_key(resource) not in completed_resource_ids
        ]

    strict: List[Dict[str, Any]] = []
    for resource in base:
        resource_key = service.repository.get_resource_key(resource)
        lesson_match = bool(lesson_resource_ids and resource_key in lesson_resource_ids)
        focus_match = service._matches_any_term(resource, focus_terms)
        context_match = service._matches_any_term(resource, lesson_terms)
        chunk_signal = (chunk_signal_map or {}).get(resource_key, {})
        chunk_match = service._safe_float(chunk_signal.get("chunk_match_score"), 0.0)
        chunk_coverage = service._safe_float(
            chunk_signal.get("chunk_coverage_score"), 0.0
        )

        if mode == "reinforce_weaknesses" and focus_terms and not (
            focus_match or lesson_match or chunk_match >= 0.52 or chunk_coverage >= 0.22
        ):
            continue
        if mode == "continue_learning" and lesson_resource_ids and not (
            lesson_match or context_match or chunk_match >= 0.5 or chunk_coverage >= 0.2
        ):
            continue
        strict.append(resource)

    filtered = strict if len(strict) >= max(limit, 3) else base
    return sorted(
        filtered,
        key=lambda resource: (
            service.repository.get_resource_key(resource) in unfinished_lesson_resource_ids,
            service.repository.get_resource_key(resource) in lesson_resource_ids,
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
