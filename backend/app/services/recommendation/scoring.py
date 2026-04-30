"""Recommendation scoring helpers."""

from __future__ import annotations

from typing import Any, Dict, Sequence


def concept_gap_fit(
    service: Any,
    *,
    mastery: float,
    confidence: float,
    focus_concepts: Sequence[str],
    resource: Dict[str, Any],
) -> float:
    topic = str(resource.get("topic") or "").lower()
    metadata = resource.get("metadata") or {}
    concepts = metadata.get("primary_concepts") or metadata.get("covered_concepts") or []
    concept_text = " ".join([topic, *(str(item).lower() for item in concepts if item)])
    focus_bonus = 0.0
    if any(str(concept).lower() in concept_text for concept in focus_concepts):
        focus_bonus = 0.18
    gap = 1.0 - ((mastery + confidence) / 2.0)
    return service._clamp(0.82 * gap + focus_bonus)


def expected_learning_gain(
    service: Any,
    *,
    quality: Dict[str, Any],
    concept_gap_fit_value: float,
) -> float:
    assessment_uplift = service._safe_float(quality.get("assessment_uplift_rate"), 0.0)
    avg_completion_rate = service._safe_float(quality.get("avg_completion_rate"), 0.0)
    clarity_readability = service._safe_float(quality.get("clarity_readability"), 0.0)
    if assessment_uplift > 0:
        return service._clamp(
            0.4 * concept_gap_fit_value
            + 0.3 * assessment_uplift
            + 0.2 * avg_completion_rate
            + 0.1 * clarity_readability
        )
    quality_score = service._safe_float(quality.get("quality_score"), 0.0)
    engagement_fit_value = service._engagement_fit(quality)
    return service._clamp(
        0.5 * concept_gap_fit_value + 0.3 * quality_score + 0.2 * engagement_fit_value
    )


def fatigue_penalty(
    service: Any,
    *,
    learner_state: Dict[str, Any],
    explanation_time: int,
) -> float:
    avg_session = max(
        service._safe_float(learner_state.get("avg_session_duration"), 15.0), 1.0
    )
    unfinished = service._safe_float(learner_state.get("unfinished_resources"), 0.0)
    learning_velocity = service._safe_float(learner_state.get("learning_velocity"), 0.5)
    time_ratio = service._clamp(explanation_time / max(avg_session, 1.0) / 2.0)
    unfinished_pressure = service._clamp(unfinished / 6.0)
    low_velocity_pressure = service._clamp((0.6 - learning_velocity) / 0.6)
    return service._clamp(
        0.45 * time_ratio + 0.35 * unfinished_pressure + 0.20 * low_velocity_pressure
    )


def compute_final_score(
    service: Any,
    *,
    components: Dict[str, float],
    weights: Any,
) -> float:
    score = (
        weights.semantic_match * components["semantic_match"]
        + weights.chunk_match_score * components["chunk_match_score"]
        + weights.chunk_coverage_score * components["chunk_coverage_score"]
        + weights.concept_gap_fit * components["concept_gap_fit"]
        + weights.difficulty_fit * components["difficulty_fit"]
        + weights.goal_fit * components["goal_fit"]
        + weights.resource_type_fit * components["resource_type_fit"]
        + weights.time_budget_fit * components["time_budget_fit"]
        + weights.quality_score * components["quality_score"]
        + weights.engagement_fit * components["engagement_fit"]
        + weights.expected_learning_gain * components["expected_learning_gain"]
        - weights.fatigue_penalty * components["fatigue_penalty"]
    )
    return service._clamp(score)
