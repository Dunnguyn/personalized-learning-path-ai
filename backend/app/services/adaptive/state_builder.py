"""Adaptive state-building helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


def normalize_target_concepts(service_cls: Any, values: Sequence[Any] | None) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for item in values or []:
        token = service_cls._normalize_concept(item)
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def question_matches_targets(
    service_cls: Any,
    question: Dict[str, Any],
    target_concepts: Sequence[str],
) -> bool:
    normalized_targets = normalize_target_concepts(service_cls, target_concepts)
    if not normalized_targets:
        return True

    metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
    candidates = {
        service_cls._normalize_concept(question.get("concept_id")),
        service_cls._normalize_concept(metadata.get("question_focus")),
    }
    for source in (
        metadata.get("covered_concepts"),
        metadata.get("target_concepts"),
    ):
        for item in source or []:
            candidates.add(service_cls._normalize_concept(item))

    return any(
        target in candidate or candidate in target
        for target in normalized_targets
        for candidate in candidates
        if candidate
    )


def extract_quiz_response_fields(service_cls: Any, quiz_payload: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = quiz_payload if isinstance(quiz_payload, dict) else {}
    return {
        "recommended_difficulty": (
            str(payload.get("recommended_difficulty"))
            if payload.get("recommended_difficulty") is not None
            else None
        ),
        "recommended_bloom_levels": [
            str(item)
            for item in (payload.get("recommended_bloom_levels") or [])
            if str(item).strip()
        ],
        "retry_strategy": (
            str(payload.get("retry_strategy"))
            if payload.get("retry_strategy") is not None
            else None
        ),
        "question_types": [
            str(item)
            for item in (payload.get("question_types") or [])
            if str(item).strip()
        ],
        "adaptive_explanation": (
            str(payload.get("adaptive_explanation"))
            if payload.get("adaptive_explanation") is not None
            else None
        ),
        "quiz": service_cls._make_json_safe(payload) if payload else None,
    }
