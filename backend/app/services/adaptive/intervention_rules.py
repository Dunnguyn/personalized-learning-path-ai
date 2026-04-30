"""Adaptive intervention-rule helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from backend.app.services.retry_strategy_service import retry_strategy_service


def resolve_target_mastery(
    service: Any,
    *,
    snapshot: Optional[Dict[str, Any]],
    target_concepts: Sequence[str],
) -> float:
    normalized_targets = service._normalize_target_concepts(target_concepts)
    mastery_by_concept = {
        service._normalize_concept(key): service._safe_float(value, 0.0)
        for key, value in ((snapshot or {}).get("mastery_by_concept") or {}).items()
        if service._normalize_concept(key)
    }
    matched_values = [
        float(value)
        for concept, value in mastery_by_concept.items()
        if any(target in concept or concept in target for target in normalized_targets)
    ]
    if matched_values:
        return min(matched_values)
    return service._safe_float((snapshot or {}).get("quiz_accuracy"), 0.0)


def build_reinforcement_quiz_config(
    service: Any,
    *,
    snapshot: Optional[Dict[str, Any]],
    target_concepts: Sequence[str],
) -> Dict[str, Any]:
    quiz_accuracy = service._safe_float((snapshot or {}).get("quiz_accuracy"), 0.0)
    completion_rate = service._safe_float((snapshot or {}).get("completion_rate"), 0.0)
    engagement_score = service._safe_float((snapshot or {}).get("engagement_score"), 0.0)
    fatigue_score = service._safe_float((snapshot or {}).get("fatigue_score"), 0.0)
    fail_streak = int((snapshot or {}).get("fail_streak") or 0)
    retry_count = int((snapshot or {}).get("retry_count") or 0)
    target_mastery = resolve_target_mastery(
        service,
        snapshot=snapshot,
        target_concepts=target_concepts,
    )

    recommended_difficulty = "beginner"
    recommended_bloom_levels = ["remember", "understand"]
    allow_llm = False
    prefer_template = True
    target_count = 5

    if (
        target_mastery >= 0.82
        and quiz_accuracy >= 0.85
        and completion_rate >= 0.75
        and fail_streak == 0
        and fatigue_score < 0.45
    ):
        recommended_difficulty = "advanced"
        recommended_bloom_levels = ["apply", "analyze"]
        allow_llm = True
        prefer_template = False
        target_count = 6
    elif target_mastery >= 0.6 and quiz_accuracy >= 0.65 and fatigue_score < 0.7:
        recommended_difficulty = "intermediate"
        recommended_bloom_levels = ["understand", "apply"]
        allow_llm = engagement_score >= 0.45
        prefer_template = not allow_llm
        target_count = 5

    if fatigue_score > 0.82:
        recommended_difficulty = "beginner"
        recommended_bloom_levels = ["remember", "understand"]
        allow_llm = False
        prefer_template = True
        target_count = 3
    elif fail_streak >= 3 or quiz_accuracy < 0.45:
        recommended_difficulty = "beginner"
        recommended_bloom_levels = ["remember", "understand"]
        allow_llm = False
        prefer_template = True
        target_count = 4

    retry_signal = max(retry_count, fail_streak, 1)
    retry_strategy = retry_strategy_service.select_retry_strategy(retry_signal)
    retry_hints = retry_strategy_service.apply_generation_hints(
        retry_strategy,
        difficulty=recommended_difficulty,
    )
    recommended_difficulty = str(
        retry_hints.get("recommended_difficulty") or recommended_difficulty
    )

    question_types = ["multiple_choice", "true_false"]
    if recommended_difficulty in {"intermediate", "advanced"} and fatigue_score < 0.75:
        question_types = ["multiple_choice", "short_answer", "true_false"]
    elif fail_streak >= 3 or fatigue_score > 0.82:
        question_types = ["multiple_choice"]

    explanation_parts = [
        f"target mastery={target_mastery:.0%}",
        f"accuracy={quiz_accuracy:.0%}",
    ]
    if fail_streak > 0:
        explanation_parts.append(f"fail streak={fail_streak}")
    if retry_count > 0:
        explanation_parts.append(f"retry count={retry_count}")
    if fatigue_score > 0:
        explanation_parts.append(f"fatigue={fatigue_score:.0%}")

    return {
        "recommended_difficulty": recommended_difficulty,
        "recommended_bloom_levels": recommended_bloom_levels,
        "allow_llm": allow_llm,
        "prefer_template": prefer_template,
        "target_count": target_count,
        "question_types": question_types,
        "retry_strategy": str(retry_hints.get("retry_strategy") or retry_strategy),
        "paraphrase_question": bool(retry_hints.get("paraphrase_question")),
        "add_explanation_before_question": bool(
            retry_hints.get("add_explanation_before_question")
        ),
        "adaptive_explanation": (
            "Quiz adapted from learner state: " + ", ".join(explanation_parts) + "."
        ),
    }
