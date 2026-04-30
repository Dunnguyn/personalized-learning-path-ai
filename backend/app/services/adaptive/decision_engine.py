"""Adaptive decision helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional


def decide_next_best_action(
    service: Any,
    *,
    user_id: str,
    path_id: Optional[str] = None,
    learner_snapshot: Optional[Dict[str, Any]] = None,
    latest_event: Optional[Dict[str, Any]] = None,
    lesson_id: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_path_id = service._resolve_latest_path_id(
        user_id=str(user_id),
        path_id=path_id or (learner_snapshot or {}).get("path_id"),
        lesson_id=lesson_id or (learner_snapshot or {}).get("current_lesson_id"),
        latest_event=latest_event,
    )
    resolved_lesson_id = str(
        lesson_id
        or (learner_snapshot or {}).get("current_lesson_id")
        or (latest_event or {}).get("lesson_id")
        or ""
    ).strip()
    if not resolved_lesson_id:
        return service._build_no_lesson_next_action(
            user_id=str(user_id),
            reason=(
                "No active lesson is available yet. Open a lesson or continue a learning path "
                "to receive the next adaptive action."
            ),
        )

    snapshot = (
        learner_snapshot
        or service.get_latest_state(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=resolved_lesson_id,
        )
        or service.recompute_state(str(user_id), resolved_path_id, resolved_lesson_id)
    )
    step = service._build_next_step(
        user_id=str(user_id),
        path_id=resolved_path_id,
        lesson_id=resolved_lesson_id,
        persist_action=False,
        snapshot=snapshot,
    )
    legacy_action = service._LEGACY_ACTION_MAP.get(step["action"], "review_summary")
    priority = (
        "high"
        if step["action"]
        in {
            service.decision_service.ASSIGN_REMEDIAL_RESOURCE,
            service.decision_service.REVIEW_WEAK_CONCEPT,
        }
        else "medium"
    )
    estimated_total_time = sum(
        int(item.get("estimated_time") or item.get("estimated_read_time") or 0)
        for item in step.get("resources", [])
        if isinstance(item, dict)
    )
    if estimated_total_time <= 0 and step.get("should_generate_quiz"):
        estimated_total_time = 10
    return {
        "user_id": str(user_id),
        "next_best_action": legacy_action,
        "reason": str(step["reason"]),
        "priority": priority,
        "recommended_mode": service._LEGACY_MODE_MAP.get(
            legacy_action, "continue_learning"
        ),
        "target_concepts": list(step.get("target_concepts") or []),
        "lesson_id": resolved_lesson_id,
        "resource_id": (
            str(step.get("resources", [{}])[0].get("resource_id"))
            if step.get("resources")
            else None
        ),
        "estimated_total_time": estimated_total_time or None,
    }
