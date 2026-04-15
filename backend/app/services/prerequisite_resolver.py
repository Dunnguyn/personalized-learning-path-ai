"""Resolve concept prerequisites and unlock status for generated lessons."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from backend.app.services.concept_graph_service import concept_graph_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.learner_state_service import learner_state_service


def _clamp(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        return default
    return max(0.0, min(numeric, 1.0))


class PrerequisiteResolver:
    """Unlock lessons from concept mastery instead of strict lesson sequence."""

    def __init__(self) -> None:
        self.mastery_threshold = _clamp(
            os.getenv("LEARNING_PATH_PREREQUISITE_MASTERY_THRESHOLD", "0.7"),
            default=0.7,
        ) or 0.7

    def estimate_concept_mastery(
        self,
        *,
        path_document: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, float]:
        mastery: Dict[str, float] = {}

        normalized_user_id = str(user_id or path_document.get("user_id") or "").strip()
        if normalized_user_id:
            try:
                snapshot = learner_state_service.compute_snapshot(
                    user_id=normalized_user_id,
                    path_id=str(path_document.get("path_id") or ""),
                )
                for concept_id, score in (snapshot.get("mastery_by_concept") or {}).items():
                    normalized_id = concept_graph_service.normalize_concept_id(concept_id)
                    if normalized_id:
                        mastery[normalized_id] = max(
                            mastery.get(normalized_id, 0.0),
                            _clamp(score),
                        )
            except Exception:
                pass

            try:
                for state in knowledge_tracing_service.get_user_concept_states(
                    user_id=normalized_user_id,
                    limit=500,
                ):
                    normalized_id = concept_graph_service.normalize_concept_id(
                        state.get("concept_id")
                    )
                    if normalized_id:
                        mastery[normalized_id] = max(
                            mastery.get(normalized_id, 0.0),
                            _clamp(state.get("p_mastery"), default=0.0),
                        )
            except Exception:
                pass

        lesson_progress = dict(path_document.get("lesson_progress") or {})
        lesson_confidence_log = dict(path_document.get("lesson_confidence_log") or {})
        for chapter in path_document.get("chapters", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "").strip()
                if not lesson_id:
                    continue
                target_concepts = self._lesson_target_concepts(lesson)
                if not target_concepts:
                    continue
                status = str(
                    lesson_progress.get(lesson_id) or lesson.get("status") or "not_started"
                ).strip().lower()
                confidence = _clamp(
                    (lesson_confidence_log.get(lesson_id) or {}).get("confidence"),
                    default=0.0,
                )
                if status in {"complete", "completed"}:
                    estimate = max(confidence, self.mastery_threshold)
                elif status == "in_progress":
                    estimate = max(confidence * 0.85, 0.35 if confidence > 0.0 else 0.0)
                else:
                    estimate = confidence * 0.6
                for concept_id in target_concepts:
                    mastery[concept_id] = max(mastery.get(concept_id, 0.0), estimate)

        return {concept_id: round(_clamp(score), 4) for concept_id, score in mastery.items()}

    def evaluate_lesson_access(
        self,
        *,
        path_document: Dict[str, Any],
        lesson_id: str,
        user_id: Optional[str] = None,
        mastery_by_concept: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        lesson = self._find_lesson(path_document=path_document, lesson_id=lesson_id)
        if not lesson:
            return {
                "can_access": False,
                "is_locked": True,
                "reason": "Lesson not found in path",
                "blocking_lesson_id": None,
                "missing_prerequisite_concepts": [],
                "blocking_concepts": [],
                "prerequisite_mastery": {},
                "bridge_recommendations": [],
                "mastery_threshold": self.mastery_threshold,
            }

        prerequisite_concepts = self._lesson_prerequisite_concepts(lesson)
        if not prerequisite_concepts:
            return {
                "can_access": True,
                "is_locked": False,
                "reason": "No prerequisite concepts required",
                "blocking_lesson_id": None,
                "missing_prerequisite_concepts": [],
                "blocking_concepts": [],
                "prerequisite_mastery": {},
                "bridge_recommendations": [],
                "mastery_threshold": self.mastery_threshold,
            }

        concept_mastery = mastery_by_concept or self.estimate_concept_mastery(
            path_document=path_document,
            user_id=user_id,
        )
        prerequisite_mastery = {
            concept_id: round(_clamp(concept_mastery.get(concept_id, 0.0)), 4)
            for concept_id in prerequisite_concepts
        }
        missing_concepts = [
            concept_id
            for concept_id in prerequisite_concepts
            if prerequisite_mastery.get(concept_id, 0.0) < self.mastery_threshold
        ]
        blocking_lesson_id = self._blocking_lesson_for_concepts(
            path_document=path_document,
            missing_concepts=missing_concepts,
        )
        bridge_recommendations = self._bridge_recommendations(
            path_document=path_document,
            missing_concepts=missing_concepts,
            prerequisite_mastery=prerequisite_mastery,
        )
        if not missing_concepts:
            return {
                "can_access": True,
                "is_locked": False,
                "reason": "All prerequisite concepts meet the mastery threshold",
                "blocking_lesson_id": None,
                "missing_prerequisite_concepts": [],
                "blocking_concepts": [],
                "prerequisite_mastery": prerequisite_mastery,
                "bridge_recommendations": [],
                "mastery_threshold": self.mastery_threshold,
            }

        labels = [
            self._concept_label(path_document=path_document, concept_id=concept_id)
            for concept_id in missing_concepts
        ]
        return {
            "can_access": False,
            "is_locked": True,
            "reason": (
                "Locked until prerequisite concept mastery reaches "
                f"{self.mastery_threshold:.0%}: {', '.join(labels[:3])}"
            ),
            "blocking_lesson_id": blocking_lesson_id,
            "missing_prerequisite_concepts": missing_concepts,
            "blocking_concepts": labels,
            "prerequisite_mastery": prerequisite_mastery,
            "bridge_recommendations": bridge_recommendations,
            "mastery_threshold": self.mastery_threshold,
        }

    def lesson_lock_statuses(
        self,
        *,
        path_document: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        mastery_by_concept = self.estimate_concept_mastery(
            path_document=path_document,
            user_id=user_id,
        )
        results: Dict[str, Dict[str, Any]] = {}
        for chapter in path_document.get("chapters", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "").strip()
                if not lesson_id:
                    continue
                resolved = self.evaluate_lesson_access(
                    path_document=path_document,
                    lesson_id=lesson_id,
                    user_id=user_id,
                    mastery_by_concept=mastery_by_concept,
                )
                results[lesson_id] = {
                    "is_locked": bool(resolved.get("is_locked")),
                    "reason": str(resolved.get("reason") or ""),
                    "blocking_lesson_id": resolved.get("blocking_lesson_id"),
                    "blocking_concepts": list(resolved.get("blocking_concepts") or []),
                    "missing_prerequisite_concepts": list(
                        resolved.get("missing_prerequisite_concepts") or []
                    ),
                    "prerequisite_mastery": dict(
                        resolved.get("prerequisite_mastery") or {}
                    ),
                    "bridge_recommendations": list(
                        resolved.get("bridge_recommendations") or []
                    ),
                    "mastery_threshold": resolved.get("mastery_threshold"),
                }
        return results

    @staticmethod
    def path_uses_concept_graph(path_document: Optional[Dict[str, Any]]) -> bool:
        if not path_document:
            return False
        concept_graph = path_document.get("concept_graph") or (
            path_document.get("metadata") or {}
        ).get("concept_graph")
        if concept_graph:
            return True
        for chapter in path_document.get("chapters", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                if (
                    lesson.get("target_concepts")
                    or lesson.get("prerequisite_concepts")
                    or (lesson.get("metadata") or {}).get("target_concepts")
                    or (lesson.get("metadata") or {}).get("prerequisite_concepts")
                ):
                    return True
        return False

    def _bridge_recommendations(
        self,
        *,
        path_document: Dict[str, Any],
        missing_concepts: Sequence[str],
        prerequisite_mastery: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        recommendations: List[Dict[str, Any]] = []
        seen_lessons: set[str] = set()
        lesson_progress = dict(path_document.get("lesson_progress") or {})
        for concept_id in missing_concepts:
            label = self._concept_label(path_document=path_document, concept_id=concept_id)
            for chapter in path_document.get("chapters", []) or []:
                for lesson in chapter.get("lessons", []) or []:
                    lesson_id = str(lesson.get("lesson_id") or "").strip()
                    if not lesson_id or lesson_id in seen_lessons:
                        continue
                    targets = self._lesson_target_concepts(lesson)
                    if concept_id not in targets:
                        continue
                    if str(lesson_progress.get(lesson_id) or lesson.get("status") or "").lower() in {
                        "complete",
                        "completed",
                    }:
                        continue
                    seen_lessons.add(lesson_id)
                    recommendations.append(
                        {
                            "type": "bridge_lesson",
                            "lesson_id": lesson_id,
                            "title": str(lesson.get("title") or label),
                            "concept_id": concept_id,
                            "concept_name": label,
                            "reason": (
                                f"Current mastery {prerequisite_mastery.get(concept_id, 0.0):.0%} "
                                f"is below the prerequisite threshold for {label}."
                            ),
                        }
                    )
            if not any(item.get("concept_id") == concept_id for item in recommendations):
                recommendations.append(
                    {
                        "type": "remedial_recommendation",
                        "lesson_id": None,
                        "title": f"Review {label}",
                        "concept_id": concept_id,
                        "concept_name": label,
                        "reason": (
                            f"Add a short remedial checkpoint because {label} is still below "
                            f"{self.mastery_threshold:.0%} mastery."
                        ),
                    }
                )
        return recommendations[:5]

    def _blocking_lesson_for_concepts(
        self,
        *,
        path_document: Dict[str, Any],
        missing_concepts: Sequence[str],
    ) -> Optional[str]:
        lesson_progress = dict(path_document.get("lesson_progress") or {})
        for concept_id in missing_concepts:
            for chapter in path_document.get("chapters", []) or []:
                for lesson in chapter.get("lessons", []) or []:
                    lesson_id = str(lesson.get("lesson_id") or "").strip()
                    if not lesson_id:
                        continue
                    if concept_id not in self._lesson_target_concepts(lesson):
                        continue
                    status = str(
                        lesson_progress.get(lesson_id) or lesson.get("status") or "not_started"
                    ).strip().lower()
                    if status not in {"complete", "completed"}:
                        return lesson_id
        return None

    def _concept_label(self, *, path_document: Dict[str, Any], concept_id: str) -> str:
        concept_graph = path_document.get("concept_graph") or (
            path_document.get("metadata") or {}
        ).get("concept_graph") or []
        for node in concept_graph:
            if concept_graph_service.normalize_concept_id(node.get("concept_id")) == concept_id:
                return str(node.get("concept_name") or concept_graph_service.concept_label(concept_id))
        return concept_graph_service.concept_label(concept_id)

    @staticmethod
    def _find_lesson(
        *,
        path_document: Dict[str, Any],
        lesson_id: str,
    ) -> Optional[Dict[str, Any]]:
        for chapter in path_document.get("chapters", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                if str(lesson.get("lesson_id") or "").strip() == str(lesson_id or "").strip():
                    return lesson
        return None

    @staticmethod
    def _lesson_target_concepts(lesson: Dict[str, Any]) -> List[str]:
        raw_values = lesson.get("target_concepts") or (lesson.get("metadata") or {}).get(
            "target_concepts"
        ) or []
        return [
            concept_graph_service.normalize_concept_id(item)
            for item in raw_values
            if concept_graph_service.normalize_concept_id(item)
        ]

    @staticmethod
    def _lesson_prerequisite_concepts(lesson: Dict[str, Any]) -> List[str]:
        raw_values = lesson.get("prerequisite_concepts") or (
            lesson.get("metadata") or {}
        ).get("prerequisite_concepts") or []
        normalized: List[str] = []
        for item in raw_values:
            concept_id = concept_graph_service.normalize_concept_id(item)
            if concept_id and concept_id not in normalized:
                normalized.append(concept_id)
        return normalized


prerequisite_resolver = PrerequisiteResolver()
