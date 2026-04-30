"""Learning-path persistence and serialization helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def serialize_learning_path(
    service: Any,
    *,
    document: Dict[str, Any],
    base_payload: Dict[str, Any],
) -> Dict[str, Any]:
    payload = dict(base_payload)
    payload["user_id"] = str(document.get("user_id") or "")
    payload["concept_graph"] = list(
        document.get("concept_graph")
        or (document.get("metadata") or {}).get("concept_graph")
        or []
    )
    payload["concept_mastery"] = dict(document.get("concept_mastery") or {})
    payload["mastery_threshold"] = service._safe_float(
        (document.get("metadata") or {}).get("mastery_threshold"),
        service.PREREQUISITE_MASTERY_THRESHOLD,
    )
    return payload


def normalize_chapters(
    *,
    chapters: List[Dict[str, Any]],
    lesson_progress: Dict[str, str],
    lesson_confidence_log: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for chapter in chapters or []:
        lessons_out = []
        for lesson in chapter.get("lessons", []) or []:
            lesson_id = str(lesson.get("lesson_id") or "")
            confidence_entry = lesson_confidence_log.get(lesson_id) or {}
            lessons_out.append(
                {
                    "lesson_id": lesson_id,
                    "title": lesson.get("title", ""),
                    "summary": lesson.get("summary"),
                    "objectives": list(lesson.get("objectives") or []),
                    "prerequisites": list(lesson.get("prerequisites") or []),
                    "target_concepts": list(lesson.get("target_concepts") or []),
                    "prerequisite_concepts": list(
                        lesson.get("prerequisite_concepts") or []
                    ),
                    "difficulty": int(lesson.get("difficulty") or 1),
                    "lesson_kind": str(lesson.get("lesson_kind") or "core"),
                    "unlock_strategy": str(
                        lesson.get("unlock_strategy") or "concept_mastery"
                    ),
                    "recommended_resources": list(
                        lesson.get("recommended_resources") or []
                    ),
                    "adaptation_metadata": dict(
                        lesson.get("adaptation_metadata") or {}
                    ),
                    "refinement": dict(lesson.get("refinement") or {}),
                    "recommended_chunk_ids": [
                        str(item)
                        for item in lesson.get("recommended_chunk_ids", []) or []
                    ],
                    "status": lesson_progress.get(
                        lesson_id, lesson.get("status", "not_started")
                    ),
                    "last_confidence": float(
                        confidence_entry.get("confidence", 0.0) or 0.0
                    ),
                    "confidence_updated_at": confidence_entry.get("updated_at"),
                }
            )
        normalized.append(
            {
                "chapter_id": str(chapter.get("chapter_id") or ""),
                "title": chapter.get("title", ""),
                "lessons": lessons_out,
            }
        )
    return normalized


def build_recommended_path(service: Any, path: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    order = 0
    for chapter in path.get("chapters", []) or []:
        for lesson in chapter.get("lessons", []) or []:
            order += 1
            adaptation_metadata = dict(lesson.get("adaptation_metadata") or {})
            target_concepts = list(lesson.get("target_concepts") or [])
            primary_concept = target_concepts[0] if target_concepts else str(order)
            items.append(
                {
                    "concept_id": service._stable_concept_numeric_id(
                        primary_concept, order=order
                    ),
                    "concept_name": str(lesson.get("title") or f"Lesson {order}"),
                    "difficulty": int(
                        lesson.get("difficulty") or min(10, 1 + ((order - 1) // 2))
                    ),
                    "bloom_level": "understand" if order <= 2 else "apply",
                    "mode": str(
                        adaptation_metadata.get("suggested_mode")
                        or "continue_learning"
                    ),
                    "priority_score": round(
                        service._safe_float(
                            adaptation_metadata.get(
                                "priority_score",
                                max(0.2, 1.0 - ((order - 1) * 0.06)),
                            )
                        ),
                        4,
                    ),
                    "resources": [
                        {
                            "title": str(item.get("title") or ""),
                            "url": item.get("url"),
                            "source": item.get("source"),
                        }
                        for item in (lesson.get("recommended_resources") or [])
                        if isinstance(item, dict)
                    ],
                    "status": service._status(lesson.get("status")),
                    "order": order,
                    "lesson_id": str(lesson.get("lesson_id") or ""),
                    "subject_id": path.get("subject_id"),
                    "topic": path.get("subject_id"),
                    "target_concepts": target_concepts,
                    "prerequisite_concepts": list(
                        lesson.get("prerequisite_concepts") or []
                    ),
                    "objectives": list(lesson.get("objectives") or []),
                    "prerequisites": list(lesson.get("prerequisites") or []),
                    "recommended_resources": list(
                        lesson.get("recommended_resources") or []
                    ),
                    "adaptation_metadata": adaptation_metadata,
                }
            )
    items.sort(
        key=lambda item: (
            0 if item.get("status") != "completed" else 1,
            -service._safe_float(item.get("priority_score"), 0.0),
            int(item.get("order") or 0),
        )
    )
    return items
