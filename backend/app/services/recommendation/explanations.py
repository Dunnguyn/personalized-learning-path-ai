"""Recommendation explanation and payload helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def build_explanation(
    service: Any,
    *,
    resource: Dict[str, Any],
    mode: str,
    learner_state: Dict[str, Any],
    goal: str,
    level: str,
    quality_score: float,
    expected_learning_gain: float,
    concept_gap_fit: float,
    difficulty_fit: float,
    lesson_context: Dict[str, Any] | None,
    chunk_match_score: float,
    matched_chunk_terms: list[str],
) -> Dict[str, Any]:
    return service.explanation_service.build_explanation(
        resource=resource,
        mode=mode,
        learner_state=learner_state,
        goal=goal,
        level=level,
        quality_score=quality_score,
        expected_learning_gain=expected_learning_gain,
        concept_gap_fit=concept_gap_fit,
        difficulty_fit=difficulty_fit,
        lesson_context=lesson_context,
        chunk_match_score=chunk_match_score,
        matched_chunk_terms=matched_chunk_terms,
    )


def build_recommendation_payload(
    service: Any,
    *,
    item: Dict[str, Any],
    rank: int,
    mode: str,
    level: str,
) -> tuple[Dict[str, Any], str]:
    resource = item["resource"]
    quality = item["quality"]
    components = dict(item["components"])
    final_score = service._safe_float(
        item.get("rerank_score"), item.get("final_base_score", 0.0)
    )
    explanation = item["explanation"]

    resource_identifier = resource.get("resource_id")
    if resource_identifier is None:
        resource_identifier = abs(hash(str(resource.get("_id")))) % 10_000_000
    try:
        serialized_resource_id: str | int = int(resource_identifier)
    except Exception:
        serialized_resource_id = str(resource_identifier)

    payload = {
        "resource_id": serialized_resource_id,
        "title": str(resource.get("title") or ""),
        "source": str(resource.get("source") or "unknown"),
        "level": str(resource.get("level") or level),
        "topic": str(resource.get("topic") or ""),
        "url": (resource.get("metadata") or {}).get("url") or resource.get("url"),
        "reason": explanation["reason"],
        "why_selected": explanation.get("why_selected") or [],
        "supports_concepts": explanation.get("supports_concepts") or [],
        "fit_level": explanation.get("fit_level"),
        "relevance_score": round(service._clamp(final_score), 4),
        "score_breakdown": components,
        "retrieval_signals": item.get("chunk_signal", {}),
        "rank_position": rank,
        "recommendation_mode": mode,
        "estimated_time": explanation["estimated_time"],
        "primary_concepts": explanation["primary_concepts"],
        "quality_score": round(service._safe_float(quality.get("quality_score"), 0.0), 4),
        "expected_learning_gain": round(
            service._safe_float(components.get("expected_learning_gain"), 0.0),
            4,
        ),
        "chunk_match_score": round(
            service._safe_float(components.get("chunk_match_score"), 0.0),
            4,
        ),
        "chunk_coverage_score": round(
            service._safe_float(components.get("chunk_coverage_score"), 0.0),
            4,
        ),
        "matched_chunk_preview": str(
            item.get("chunk_signal", {}).get("matched_chunk_preview") or ""
        ),
        "matched_chunk_terms": item.get("chunk_signal", {}).get("matched_chunk_terms")
        or [],
        "supporting_chunk_count": int(
            item.get("chunk_signal", {}).get("supporting_chunk_count") or 0
        ),
    }
    return payload, str(resource_identifier)


def persist_explanation_record(
    service: Any,
    *,
    user_id: str | int,
    resource_identifier: str,
    mode: str,
    payload: Dict[str, Any],
) -> None:
    service.explanation_collection.update_one(
        {
            "user_id": str(user_id),
            "resource_key": str(resource_identifier),
            "mode": mode,
        },
        {"$set": {**payload, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
