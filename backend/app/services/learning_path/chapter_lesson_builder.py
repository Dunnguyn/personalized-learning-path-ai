"""Learning-path chapter and lesson building helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from bson import ObjectId

from backend.app.services.learning_path.curriculum_sizing import (
    resolve_curriculum_size_policy,
)


def generate_curriculum_outline(
    service: Any,
    *,
    subject_label: str,
    goal: str,
    level: str,
    planner_input: Dict[str, Any],
    fallback: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    size_policy = resolve_curriculum_size_policy(
        subject_id=str(planner_input.get("subject_id") or ""),
        goal=goal,
        level=level,
        planner_input=planner_input,
    )
    prompt = service._build_learning_path_outline_prompt_helper(
        subject_label,
        goal,
        level,
        target_chapter_count=max(
            int(size_policy.get("min_chapters") or 2),
            min(int(size_policy.get("target_chapters") or 3), len(fallback) or 3),
        ),
        planner_input=planner_input,
    )
    payload = service._generate_curriculum_json_payload(
        prompt=prompt,
        max_output_tokens=900,
    )
    chapter_items = payload.get("chapters", []) if isinstance(payload, dict) else []
    outline: List[Dict[str, Any]] = []
    lesson_min = int(size_policy.get("lessons_per_chapter_min") or 2)
    lesson_max = int(size_policy.get("lessons_per_chapter_max") or 4)
    for index, fallback_chapter in enumerate(fallback):
        item = (
            chapter_items[index]
            if index < len(chapter_items) and isinstance(chapter_items[index], dict)
            else {}
        )
        fallback_lessons = list(fallback_chapter.get("lessons") or [])
        lesson_count = len(fallback_lessons) or 3
        try:
            lesson_count = int(item.get("lesson_count") or lesson_count)
        except Exception:
            lesson_count = len(fallback_lessons) or 3
        outline.append(
            {
                "title": str(item.get("title") or fallback_chapter.get("title") or "").strip()
                or f"Chapter {index + 1}",
                "focus": str(
                    item.get("focus")
                    or (fallback_lessons[0].get("summary") if fallback_lessons else "")
                    or fallback_chapter.get("title")
                    or ""
                ).strip(),
                    "lesson_count": max(lesson_min, min(lesson_max, lesson_count)),
                }
            )
    return outline


def generate_curriculum_chapter(
    service: Any,
    *,
    subject_label: str,
    goal: str,
    level: str,
    planner_input: Dict[str, Any],
    outline_item: Dict[str, Any],
    chapter_index: int,
    total_chapters: int,
    prior_chapter_titles: List[str],
    fallback_chapter: Dict[str, Any],
) -> Dict[str, Any]:
    size_policy = resolve_curriculum_size_policy(
        subject_id=str(planner_input.get("subject_id") or ""),
        goal=goal,
        level=level,
        planner_input=planner_input,
    )
    lesson_min = int(size_policy.get("lessons_per_chapter_min") or 2)
    lesson_max = int(size_policy.get("lessons_per_chapter_max") or 4)
    prompt = service._build_learning_path_chapter_prompt_helper(
        subject_label,
        goal,
        level,
        chapter_title=str(
            outline_item.get("title") or fallback_chapter.get("title") or ""
        ).strip(),
        chapter_focus=str(outline_item.get("focus") or "").strip(),
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        target_lesson_count=max(
            lesson_min,
            min(
                lesson_max,
                int(
                    outline_item.get("lesson_count")
                    or len(fallback_chapter.get("lessons") or [])
                    or lesson_min
                ),
            ),
        ),
        prior_chapter_titles=prior_chapter_titles,
        planner_input=planner_input,
    )
    payload = service._generate_curriculum_json_payload(
        prompt=prompt,
        max_output_tokens=1600,
    )
    lessons = payload.get("lessons", []) if isinstance(payload, dict) else []
    if not isinstance(lessons, list) or not lessons:
        return {
            "title": str(
                outline_item.get("title") or fallback_chapter.get("title") or ""
            ).strip(),
            "lessons": list(fallback_chapter.get("lessons") or []),
            "_source": "fallback",
        }
    return {
        "title": str(
            outline_item.get("title")
            or payload.get("title")
            or fallback_chapter.get("title")
            or ""
        ).strip(),
        "lessons": lessons,
        "_source": "ai",
    }


def resource_payload(service: Any, resource_ids: List[str]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for resource_id in [str(item or "").strip() for item in resource_ids]:
        if not resource_id:
            continue
        resource = None
        if ObjectId.is_valid(resource_id):
            try:
                resource = service.resource_repository.get(resource_id)
            except Exception:
                resource = None
        if not resource:
            resource = service.resource_repository.collection.find_one(
                {"resource_id": resource_id}
            )
        if not resource:
            continue
        metadata = resource.get("metadata") or {}
        payload.append(
            {
                "resource_id": str(resource.get("_id") or resource_id),
                "title": str(resource.get("title") or ""),
                "type": str(resource.get("type") or "text"),
                "source": str(resource.get("source") or ""),
                "topic": str(resource.get("topic") or ""),
                "level": str(metadata.get("level") or ""),
                "url": metadata.get("url"),
            }
        )
        if len(payload) >= 4:
            break
    return payload


def adaptation_metadata(
    service: Any,
    *,
    planner_input: Dict[str, Any],
    snapshot: Dict[str, Any],
    lesson_order: int,
    total_lessons: int,
) -> Dict[str, Any]:
    learner_model = (
        planner_input.get("learner_model")
        if isinstance(planner_input.get("learner_model"), dict)
        else {}
    )
    mastery = service._safe_float(
        learner_model.get("current_mastery", planner_input.get("current_mastery")),
        0.0,
    )
    completion = service._safe_float(planner_input.get("completion_rate"), 0.0)
    weak_concepts = service._dedupe(
        list(
            learner_model.get("weak_concepts")
            or planner_input.get("weak_concepts")
            or []
        ),
        limit=3,
    )
    mode = "continue_learning"
    if weak_concepts and mastery < 0.6:
        mode = "reinforce_weaknesses"
    elif completion >= 0.68 and mastery >= 0.72:
        mode = "learn_new"

    total_lessons = max(int(total_lessons or 1), 1)
    urgency = service._clamp((lesson_order / total_lessons), 0.0, 1.0)
    confidence = service._safe_float(snapshot.get("confidence_score"), 0.0)
    friction = service._safe_float(
        learner_model.get("friction_score", snapshot.get("friction_score")),
        0.0,
    )
    priority_score = service._clamp(
        0.45 * urgency + 0.25 * (1.0 - mastery) + 0.2 * (1.0 - confidence) + 0.1 * friction
    )
    return {
        "suggested_mode": mode,
        "priority_score": round(priority_score, 4),
        "weak_concepts": weak_concepts,
        "current_mastery": round(mastery, 4),
        "completion_rate": round(completion, 4),
        "engagement_score": round(
            service._safe_float(
                learner_model.get("engagement_score", snapshot.get("engagement_score")),
                0.0,
            ),
            4,
        ),
        "friction_score": round(friction, 4),
        "time_budget_score": round(
            service._safe_float(learner_model.get("time_budget_score"), 0.0), 4
        ),
    }
