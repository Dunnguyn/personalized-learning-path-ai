"""Adaptive next-step payload helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_no_lesson_next_action(*, user_id: str, reason: str) -> Dict[str, Any]:
    return {
        "user_id": str(user_id),
        "next_best_action": "review_summary",
        "reason": reason,
        "priority": "medium",
        "recommended_mode": "continue_learning",
        "target_concepts": [],
        "lesson_id": None,
        "resource_id": None,
        "estimated_total_time": None,
    }


def build_no_lesson_recommendation(
    *,
    user_id: str,
    reason: str,
    items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    safe_items = list(items or [])
    estimated_total_time = sum(
        int(item.get("estimated_time") or item.get("estimated_read_time") or 0)
        for item in safe_items
        if isinstance(item, dict)
    )
    return {
        "user_id": str(user_id),
        "action": "review_summary",
        "recommendation_type": "resource",
        "recommendation_mode": "continue_learning",
        "items": safe_items,
        "reason": reason,
        "target_concepts": [],
        "estimated_total_time": estimated_total_time,
        "lesson_id": None,
        "resource_id": str(safe_items[0].get("resource_id"))
        if safe_items and safe_items[0].get("resource_id")
        else None,
    }
