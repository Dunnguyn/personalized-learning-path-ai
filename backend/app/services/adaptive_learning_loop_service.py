"""Adaptive learning loop built on top of existing recommendation services."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.repositories import (
    ExpectedLearningGainRepository,
    LearnerStateSnapshotRepository,
    LearningEventRepository,
    LessonRepository,
    RecommendationRepository,
    ResourceRepository,
)
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.hybrid_recommendation_service import (
    hybrid_recommendation_service,
)
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.lesson_chunk_service import lesson_chunk_service


class AdaptiveLearningLoopService:
    """Ingest learner events, refresh state snapshots, and propose the next action."""

    _ACTION_TO_MODE = {
        "continue_resource": "continue_learning",
        "resume_unfinished": "continue_learning",
        "review_summary": "quick_review",
        "practice_quiz": "quick_review",
        "retry_with_easier_resource": "reinforce_weaknesses",
        "study_worked_example": "reinforce_weaknesses",
        "study_misconception_fix": "reinforce_weaknesses",
        "reinforce_weak_concept": "reinforce_weaknesses",
        "move_to_next_lesson": "learn_new",
        "return_to_prerequisite": "continue_learning",
        "switch_format_to_video": "quick_review",
        "switch_format_to_text": "continue_learning",
        "quick_review_session": "quick_review",
    }

    def __init__(self) -> None:
        self.db = get_db()
        self.users = self.db.users
        self.progress = self.db.progress
        self.learning_paths = self.db.learning_paths
        self.resource_quality_stats = self.db.resource_quality_stats
        self.expected_gain_stats = ExpectedLearningGainRepository()
        self.learning_event_repository = LearningEventRepository()
        self.snapshot_repository = LearnerStateSnapshotRepository()
        self.lesson_repository = LessonRepository()
        self.resource_repository = ResourceRepository()
        self.recommendation_repository = RecommendationRepository()
        self.learner_state_service = learner_state_service
        self.hybrid_recommendation_service = hybrid_recommendation_service
        self.lesson_chunk_service = lesson_chunk_service

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _normalize_string_list(values: Sequence[Any] | None) -> List[str]:
        return [str(item).strip() for item in values or [] if str(item).strip()]

    @staticmethod
    def _average(values: Sequence[float]) -> float:
        normalized = [float(item) for item in values]
        if not normalized:
            return 0.0
        return sum(normalized) / len(normalized)

    @staticmethod
    def _is_object_id(value: Any) -> bool:
        try:
            return ObjectId.is_valid(str(value))
        except Exception:
            return False

    def _resolve_user_profile(self, user_id: str) -> Dict[str, Any]:
        user = None
        if self._is_object_id(user_id):
            user = self.users.find_one({"_id": ObjectId(user_id)})
        if user is None:
            user = self.users.find_one({"user_id": user_id})
        return user or {}

    def _resolve_goal_and_level(
        self,
        *,
        user_id: str,
        goal: Optional[str],
        level: Optional[str],
        lesson_id: Optional[str] = None,
    ) -> tuple[str, str]:
        user = self._resolve_user_profile(user_id)
        resolved_goal = str(goal or user.get("learning_goal") or "").strip()
        resolved_level = str(level or user.get("level") or "beginner").strip().lower()

        if not resolved_goal and lesson_id and self._is_object_id(lesson_id):
            lesson = self.lesson_repository.get(lesson_id)
            if lesson:
                resolved_goal = str(
                    lesson.get("topic")
                    or lesson.get("title")
                    or lesson.get("summary")
                    or ""
                ).strip()
                resolved_level = str(
                    lesson.get("level") or resolved_level or "beginner"
                ).strip().lower()

        if not resolved_goal:
            latest_path = self.learning_paths.find_one(
                {"user_id": str(user_id)},
                sort=[("created_at", -1)],
            )
            if latest_path:
                resolved_goal = str(latest_path.get("goal") or "").strip()
                resolved_level = str(
                    latest_path.get("level") or resolved_level or "beginner"
                ).strip().lower()

        if not resolved_goal:
            resolved_goal = "Continue current learning path"

        if resolved_level not in {"beginner", "intermediate", "advanced"}:
            resolved_level = "beginner"

        return resolved_goal, resolved_level

    def _resource_lookup(self, resource_id: str | None) -> Optional[Dict[str, Any]]:
        if not resource_id:
            return None
        if self._is_object_id(resource_id):
            resource = self.resource_repository.get(resource_id)
            if resource:
                return resource
        for query in (
            {"resource_id": resource_id},
            {"resource_id": int(resource_id)} if str(resource_id).isdigit() else None,
        ):
            if not query:
                continue
            resource = self.resource_repository.collection.find_one(query)
            if resource:
                return resource
        return None

    def _derive_mastery_maps(self, user_id: str) -> tuple[Dict[str, float], Dict[str, float]]:
        mastery_by_concept: Dict[str, float] = {}
        confidence_by_concept: Dict[str, float] = {}
        for row in self.recommendation_repository.get_user_progress(user_id):
            concept_id = str(row.get("concept_id") or "").strip()
            if not concept_id:
                continue
            mastery_by_concept[concept_id] = round(
                self._clamp(self._safe_float(row.get("mastery"), 0.0)),
                4,
            )
            confidence_by_concept[concept_id] = round(
                self._clamp(self._safe_float(row.get("confidence"), 0.0)),
                4,
            )
        return mastery_by_concept, confidence_by_concept

    def _recent_learning_events(self, user_id: str, *, days: int = 30) -> List[Dict[str, Any]]:
        since = self._utcnow() - timedelta(days=max(days, 1))
        return self.learning_event_repository.list_since(
            since=since,
            user_id=user_id,
            limit=2000,
        )

    def _calculate_quiz_fail_streak(self, events: Sequence[Dict[str, Any]]) -> tuple[int, float]:
        streak = 0
        latest_score = 0.0
        ordered = sorted(
            events,
            key=lambda item: item.get("created_at") or datetime.min,
            reverse=True,
        )
        for event in ordered:
            if str(event.get("event_type") or "") != "quiz_submitted":
                continue
            score = self._safe_float((event.get("metadata") or {}).get("score"), 0.0)
            if latest_score == 0.0:
                latest_score = score
            if score < 0.6:
                streak += 1
            else:
                break
        return streak, latest_score

    def _unfinished_resource_ids(self, events: Sequence[Dict[str, Any]]) -> List[str]:
        opened_order: List[str] = []
        completed_ids: set[str] = set()
        ordered = sorted(events, key=lambda item: item.get("created_at") or datetime.min)
        for event in ordered:
            resource_id = str(event.get("resource_id") or "").strip()
            if not resource_id:
                continue
            event_type = str(event.get("event_type") or "")
            if event_type in {"resource_opened", "resource_abandoned"} and resource_id not in opened_order:
                opened_order.append(resource_id)
            if event_type == "resource_completed":
                completed_ids.add(resource_id)
        return [
            resource_id
            for resource_id in reversed(opened_order)
            if resource_id not in completed_ids
        ]

    def _resource_abandonment_rate(self, events: Sequence[Dict[str, Any]]) -> float:
        opened = 0
        abandoned = 0
        for event in events:
            event_type = str(event.get("event_type") or "")
            if event_type == "resource_opened":
                opened += 1
            elif event_type == "resource_abandoned":
                abandoned += 1
        if opened <= 0:
            return 0.0
        return self._clamp(abandoned / opened)

    def _infer_preferred_format(self, user_id: str) -> str:
        preference = self.recommendation_repository.get_user_format_preference(user_id)
        if not preference:
            return "text"
        format_key, _ = max(preference.items(), key=lambda item: item[1])
        if format_key in {"youtube", "video"}:
            return "video"
        return "text"

    def _resolve_lesson_context(
        self,
        *,
        user_id: str,
        lesson_id: Optional[str],
        latest_event: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        resolved_lesson_id = (
            str(lesson_id or (latest_event or {}).get("lesson_id") or "").strip()
        )
        if not resolved_lesson_id:
            latest_lesson_event = self.learning_event_repository.latest_one(
                user_id,
                event_type="lesson_started",
            )
            if latest_lesson_event:
                resolved_lesson_id = str(
                    latest_lesson_event.get("lesson_id") or ""
                ).strip()
        if not resolved_lesson_id or not self._is_object_id(resolved_lesson_id):
            return None
        lesson = self.lesson_repository.get(resolved_lesson_id)
        return lesson if lesson else None

    def _lesson_mastery_average(
        self,
        *,
        lesson: Optional[Dict[str, Any]],
        mastery_by_concept: Dict[str, float],
        fallback_average: float,
    ) -> float:
        if not lesson:
            return fallback_average
        lesson_terms = self._normalize_string_list(
            list(lesson.get("keywords") or []) + list(lesson.get("learning_objectives") or [])
        )
        if not lesson_terms:
            return fallback_average
        lowered = {key.lower(): value for key, value in mastery_by_concept.items()}
        matched: List[float] = []
        for term in lesson_terms:
            if term.lower() in lowered:
                matched.append(lowered[term.lower()])
        return round(self._average(matched) if matched else fallback_average, 4)

    def _prerequisite_satisfaction(self, user_id: str, lesson: Optional[Dict[str, Any]]) -> float:
        if not lesson:
            return 1.0
        chapter_id = lesson.get("chapter_id")
        if not chapter_id:
            return 1.0
        prior_lessons = [
            row
            for row in self.lesson_repository.list_by_chapter(chapter_id)
            if int(row.get("order") or 0) < int(lesson.get("order") or 0)
        ]
        if not prior_lessons:
            return 1.0
        completed = 0
        for prior_lesson in prior_lessons:
            latest_completion = self.learning_event_repository.latest_one(
                user_id,
                lesson_id=str(prior_lesson.get("_id")),
                event_type="lesson_completed",
            )
            if latest_completion is not None:
                completed += 1
        return round(self._clamp(completed / max(len(prior_lessons), 1)), 4)

    def ingest_learning_event(
        self,
        *,
        user_id: str,
        event_type: str,
        resource_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        path_id: Optional[str] = None,
        concept_ids: Sequence[str] | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "event_id": f"le_{uuid.uuid4().hex}",
            "user_id": str(user_id),
            "event_type": str(event_type),
            "resource_id": str(resource_id) if resource_id else None,
            "lesson_id": str(lesson_id) if lesson_id else None,
            "path_id": str(path_id) if path_id else None,
            "concept_ids": self._normalize_string_list(concept_ids),
            "metadata": dict(metadata or {}),
            "created_at": self._utcnow(),
        }
        created = self.learning_event_repository.create_event(payload)
        event_logging_service.log_event(
            str(event_type),
            user_id=str(user_id),
            resource_id=resource_id,
            lesson_id=lesson_id,
            path_id=path_id,
            success=True,
            metadata=dict(metadata or {}),
        )

        snapshot = self.update_learner_state(user_id=user_id, latest_event=created)
        action = self.decide_next_best_action(
            user_id=user_id,
            learner_snapshot=snapshot,
            latest_event=created,
            lesson_id=lesson_id,
        )
        self._persist_last_action(user_id, action["next_best_action"])
        return created

    def update_learner_state(
        self,
        *,
        user_id: str,
        latest_event: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        base_state = dict(self.learner_state_service.build_state(user_id))
        mastery_by_concept, confidence_by_concept = self._derive_mastery_maps(user_id)
        recent_events = self._recent_learning_events(user_id, days=30)
        latest_event = latest_event or (recent_events[0] if recent_events else None)
        quiz_fail_streak, latest_quiz_score = self._calculate_quiz_fail_streak(recent_events)
        unfinished_resource_ids = self._unfinished_resource_ids(recent_events)
        frustration_score = max(
            self._safe_float(base_state.get("frustration_score"), 0.0),
            self._clamp(
                0.45 * self._safe_float(base_state.get("frustration_score"), 0.0)
                + 0.35 * self._clamp(quiz_fail_streak / 4.0)
                + 0.20 * self._resource_abandonment_rate(recent_events)
            ),
        )
        average_mastery = self._average(list(mastery_by_concept.values()))
        risk_level = "low"
        if frustration_score >= 0.7 or quiz_fail_streak >= 3 or average_mastery < 0.35:
            risk_level = "high"
        elif frustration_score >= 0.45 or quiz_fail_streak >= 1 or average_mastery < 0.6:
            risk_level = "medium"

        previous_snapshot = self.snapshot_repository.get_latest(user_id) or {}
        snapshot = {
            "user_id": str(user_id),
            "snapshot_time": self._utcnow(),
            "mastery_by_concept": mastery_by_concept,
            "confidence_by_concept": confidence_by_concept,
            "recent_active_days": int(base_state.get("recent_active_days") or 0),
            "avg_session_duration": round(
                self._safe_float(base_state.get("avg_session_duration"), 12.0),
                2,
            ),
            "unfinished_resources": len(unfinished_resource_ids),
            "unfinished_resource_ids": unfinished_resource_ids,
            "quiz_fail_streak": quiz_fail_streak,
            "retry_count": int(base_state.get("retry_count") or 0),
            "learning_velocity": round(
                self._safe_float(base_state.get("learning_velocity"), 0.0),
                4,
            ),
            "preferred_time_window": str(
                base_state.get("preferred_time_window") or "evening"
            ),
            "current_focus_concepts": list(base_state.get("current_focus_concepts") or []),
            "frustration_score": round(self._clamp(frustration_score), 4),
            "recovery_need_flag": bool(
                base_state.get("recovery_need_flag")
                or frustration_score >= 0.6
                or (average_mastery < 0.4 and quiz_fail_streak >= 2)
            ),
            "risk_level": risk_level,
            "last_event_type": str(latest_event.get("event_type") or "") if latest_event else None,
            "last_recommended_action": previous_snapshot.get("last_recommended_action"),
            "last_quiz_score": round(latest_quiz_score, 4),
            "avg_mastery": round(average_mastery, 4),
            "preferred_format": self._infer_preferred_format(user_id),
            "resource_abandonment_rate": round(
                self._resource_abandonment_rate(recent_events),
                4,
            ),
        }
        if not persist:
            return snapshot
        return self.snapshot_repository.upsert_latest(snapshot)

    def decide_next_best_action(
        self,
        *,
        user_id: str,
        learner_snapshot: Optional[Dict[str, Any]] = None,
        latest_event: Optional[Dict[str, Any]] = None,
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot = learner_snapshot or self.snapshot_repository.get_latest(user_id)
        if not snapshot:
            snapshot = self.update_learner_state(user_id=user_id, latest_event=latest_event)
        latest_event = latest_event or self.learning_event_repository.latest_one(user_id)
        lesson = self._resolve_lesson_context(
            user_id=user_id,
            lesson_id=lesson_id,
            latest_event=latest_event,
        )
        mastery_by_concept = dict(snapshot.get("mastery_by_concept") or {})
        confidence_by_concept = dict(snapshot.get("confidence_by_concept") or {})
        avg_mastery = self._safe_float(
            snapshot.get("avg_mastery"),
            self._average(list(mastery_by_concept.values())),
        )
        avg_confidence = self._average(list(confidence_by_concept.values()))
        lowest_concept = None
        if mastery_by_concept:
            lowest_concept = min(mastery_by_concept.items(), key=lambda item: item[1])[0]
        prerequisite_satisfaction = self._prerequisite_satisfaction(user_id, lesson)
        resource_abandonment_rate = self._safe_float(
            snapshot.get("resource_abandonment_rate"),
            0.0,
        )
        preferred_format = str(snapshot.get("preferred_format") or "text")
        latest_event_type = str((latest_event or {}).get("event_type") or "")
        latest_metadata = dict((latest_event or {}).get("metadata") or {})
        latest_quiz_score = self._safe_float(
            latest_metadata.get("score"),
            self._safe_float(snapshot.get("last_quiz_score"), 0.0),
        )
        lesson_mastery = self._lesson_mastery_average(
            lesson=lesson,
            mastery_by_concept=mastery_by_concept,
            fallback_average=avg_mastery,
        )

        action = "continue_resource"
        reason = "Continue the current learning flow with the most relevant supporting material."
        priority = "medium"

        if prerequisite_satisfaction < 0.5:
            action = "return_to_prerequisite"
            reason = "A prerequisite lesson is still weak, so it should be reviewed before moving on."
            priority = "high"
        elif self._safe_float(snapshot.get("frustration_score"), 0.0) >= 0.7:
            action = "quick_review_session"
            reason = "Recent signals show high frustration, so a short review is safer than a heavy lesson."
            priority = "high"
        elif latest_event_type == "quiz_submitted" and latest_quiz_score < 0.4:
            action = "retry_with_easier_resource"
            reason = "The most recent quiz score was low, so an easier resource should come before retrying."
            priority = "high"
        elif int(snapshot.get("quiz_fail_streak") or 0) >= 2:
            action = "study_worked_example"
            reason = "Recent quiz failures suggest a worked example is needed before the next attempt."
            priority = "high"
        elif avg_confidence < 0.4 and avg_mastery >= 0.4:
            action = "review_summary"
            reason = "Confidence dropped more than mastery, so a short summary can stabilize understanding."
            priority = "medium"
        elif latest_event_type == "lesson_completed" and lesson_mastery >= 0.75:
            action = "move_to_next_lesson"
            reason = "The current lesson is completed with good mastery, so the next lesson is unlocked."
            priority = "medium"
        elif resource_abandonment_rate >= 0.45 and preferred_format != "text":
            action = "switch_format_to_video"
            reason = "Text resources are being abandoned often, so a video format is a better fit right now."
            priority = "medium"
        elif resource_abandonment_rate >= 0.45 and preferred_format == "text":
            action = "switch_format_to_text"
            reason = "Video-heavy study has low completion recently, so switching back to text can reduce fatigue."
            priority = "medium"
        elif int(snapshot.get("unfinished_resources") or 0) > 0:
            action = "resume_unfinished"
            reason = "There is unfinished material that should be completed before opening more new content."
            priority = "medium"
        elif lowest_concept and self._safe_float(mastery_by_concept.get(lowest_concept), 0.0) < 0.55:
            action = "reinforce_weak_concept"
            reason = f"The weakest concept is {lowest_concept}, so reinforcement should happen before expansion."
            priority = "medium"

        return {
            "user_id": str(user_id),
            "next_best_action": action,
            "reason": reason,
            "priority": priority,
            "recommended_mode": self._ACTION_TO_MODE.get(action, "continue_learning"),
            "target_concepts": [lowest_concept]
            if lowest_concept
            else list(snapshot.get("current_focus_concepts") or [])[:2],
            "lesson_id": str(lesson.get("_id")) if lesson else None,
            "resource_id": (
                str((snapshot.get("unfinished_resource_ids") or [None])[0])
                if action in {"continue_resource", "resume_unfinished"}
                else None
            ),
            "estimated_total_time": 10
            if action in {"quick_review_session", "review_summary"}
            else 15,
        }

    def _persist_last_action(self, user_id: str, action: str) -> None:
        latest_snapshot = self.snapshot_repository.get_latest(user_id)
        if not latest_snapshot:
            return
        self.snapshot_repository.collection.update_one(
            {"_id": latest_snapshot["_id"]},
            {"$set": {"last_recommended_action": str(action)}},
        )

    def _load_or_build_lesson_chunks(self, lesson_id: str) -> Dict[str, Any]:
        try:
            return self.lesson_chunk_service.get_recommendation(lesson_id)
        except Exception:
            return self.lesson_chunk_service.recommend_chunks(
                lesson_id=lesson_id,
                max_chunks=6,
                metadata={"mode": "assessment_boost"},
            )

    def _resource_item_from_document(
        self,
        resource: Dict[str, Any],
        *,
        reason: str,
    ) -> Dict[str, Any]:
        metadata = resource.get("metadata") or {}
        estimated_time = int(metadata.get("estimated_time") or 12)
        resource_identifier = resource.get("resource_id") or resource.get("_id")
        return {
            "resource_id": str(resource_identifier),
            "title": str(resource.get("title") or ""),
            "topic": str(resource.get("topic") or ""),
            "source": str(resource.get("source") or ""),
            "level": str(resource.get("level") or metadata.get("level") or "beginner"),
            "url": metadata.get("url") or resource.get("url"),
            "estimated_time": estimated_time,
            "reason": reason,
        }

    def _select_chunk_items(
        self,
        *,
        lesson_id: str,
        role: str,
        fallback_roles: Sequence[str] = (),
    ) -> List[Dict[str, Any]]:
        recommendation = self._load_or_build_lesson_chunks(lesson_id)
        recommended_chunks = list(recommendation.get("recommended_chunks") or [])
        target_roles = [role, *fallback_roles]
        selected = [
            item
            for item in recommended_chunks
            if str(item.get("instruction_role") or "") in target_roles
        ]
        if not selected:
            selected = recommended_chunks[:3]
        return selected[:3]

    def _find_adjacent_lesson(
        self,
        *,
        lesson_id: str,
        direction: str,
    ) -> Optional[Dict[str, Any]]:
        if not self._is_object_id(lesson_id):
            return None
        lesson = self.lesson_repository.get(lesson_id)
        if not lesson:
            return None
        chapter_lessons = self.lesson_repository.list_by_chapter(lesson["chapter_id"])
        ordered = sorted(chapter_lessons, key=lambda item: int(item.get("order") or 0))
        index_map = {str(item["_id"]): idx for idx, item in enumerate(ordered)}
        current_index = index_map.get(str(lesson["_id"]))
        if current_index is None:
            return None
        target_index = current_index + (1 if direction == "next" else -1)
        if target_index < 0 or target_index >= len(ordered):
            return None
        return ordered[target_index]

    def generate_adaptive_recommendation(
        self,
        *,
        user_id: str,
        goal: Optional[str] = None,
        level: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot = self.snapshot_repository.get_latest(user_id) or self.update_learner_state(
            user_id=user_id
        )
        action = self.decide_next_best_action(
            user_id=user_id,
            learner_snapshot=snapshot,
            lesson_id=lesson_id,
        )
        resolved_goal, resolved_level = self._resolve_goal_and_level(
            user_id=user_id,
            goal=goal,
            level=level,
            lesson_id=lesson_id or action.get("lesson_id"),
        )
        action_name = str(action.get("next_best_action") or "continue_resource")
        recommendation_mode = self._ACTION_TO_MODE.get(action_name, "continue_learning")
        items: List[Dict[str, Any]] = []
        recommendation_type = "resource"

        if action_name in {"resume_unfinished", "continue_resource"}:
            for resource_id in list(snapshot.get("unfinished_resource_ids") or [])[:3]:
                resource = self._resource_lookup(resource_id)
                if resource:
                    items.append(
                        self._resource_item_from_document(
                            resource,
                            reason="Resume this unfinished resource before moving to new material.",
                        )
                    )
            if not items:
                recommended = self.hybrid_recommendation_service.recommend_resources(
                    user_id=user_id,
                    goal=resolved_goal,
                    level=resolved_level,
                    limit=3,
                    enable_reranking=True,
                    mode="continue_learning",
                )
                items = recommended.get("recommended", [])[:3]
        elif action_name == "review_summary":
            recommendation_type = "chunk"
            if action.get("lesson_id"):
                items = self._select_chunk_items(
                    lesson_id=str(action["lesson_id"]),
                    role="summary",
                    fallback_roles=("introduction", "explanation"),
                )
        elif action_name == "study_worked_example":
            recommendation_type = "chunk"
            if action.get("lesson_id"):
                items = self._select_chunk_items(
                    lesson_id=str(action["lesson_id"]),
                    role="worked_example",
                    fallback_roles=("practice_hint", "explanation"),
                )
        elif action_name == "study_misconception_fix":
            recommendation_type = "chunk"
            if action.get("lesson_id"):
                items = self._select_chunk_items(
                    lesson_id=str(action["lesson_id"]),
                    role="misconception_fix",
                    fallback_roles=("summary", "worked_example"),
                )
        elif action_name == "move_to_next_lesson":
            recommendation_type = "lesson"
            next_lesson = self._find_adjacent_lesson(
                lesson_id=str(action.get("lesson_id") or lesson_id or ""),
                direction="next",
            )
            if next_lesson:
                items = [
                    {
                        "lesson_id": str(next_lesson.get("_id")),
                        "title": str(next_lesson.get("title") or ""),
                        "summary": str(next_lesson.get("summary") or ""),
                        "level": str(next_lesson.get("level") or resolved_level),
                        "estimated_time": 18,
                    }
                ]
        elif action_name == "return_to_prerequisite":
            recommendation_type = "lesson"
            previous_lesson = self._find_adjacent_lesson(
                lesson_id=str(action.get("lesson_id") or lesson_id or ""),
                direction="previous",
            )
            if previous_lesson:
                items = [
                    {
                        "lesson_id": str(previous_lesson.get("_id")),
                        "title": str(previous_lesson.get("title") or ""),
                        "summary": str(previous_lesson.get("summary") or ""),
                        "level": str(previous_lesson.get("level") or resolved_level),
                        "estimated_time": 15,
                    }
                ]
        elif action_name == "practice_quiz":
            recommendation_type = "lesson"
            items = [
                {
                    "lesson_id": str(action.get("lesson_id") or lesson_id or ""),
                    "action": "practice_quiz",
                    "target_count": 5,
                    "difficulty": "beginner",
                    "estimated_time": 10,
                }
            ]
        else:
            recommended = self.hybrid_recommendation_service.recommend_resources(
                user_id=user_id,
                goal=resolved_goal,
                level=resolved_level,
                limit=4,
                enable_reranking=True,
                mode=recommendation_mode,
            )
            items = recommended.get("recommended", [])[:4]
            if action_name == "switch_format_to_video":
                filtered = [
                    item
                    for item in items
                    if str(item.get("source") or "").lower() == "youtube"
                    or str(item.get("type") or "").lower() == "video"
                ]
                if filtered:
                    items = filtered
            elif action_name == "switch_format_to_text":
                filtered = [
                    item
                    for item in items
                    if str(item.get("source") or "").lower() in {"pdf", "web", "manual"}
                ]
                if filtered:
                    items = filtered

        if not items:
            recommended = self.hybrid_recommendation_service.recommend_resources(
                user_id=user_id,
                goal=resolved_goal,
                level=resolved_level,
                limit=3,
                enable_reranking=True,
                mode=recommendation_mode,
            )
            items = recommended.get("recommended", [])[:3]
            recommendation_type = "resource"

        estimated_total_time = 0
        for item in items:
            estimated_total_time += int(
                item.get("estimated_time") or item.get("estimated_read_time") or 0
            )

        self._persist_last_action(user_id, action_name)
        return {
            "user_id": str(user_id),
            "action": action_name,
            "recommendation_type": recommendation_type,
            "recommendation_mode": recommendation_mode,
            "items": items,
            "reason": str(action.get("reason") or ""),
            "target_concepts": list(action.get("target_concepts") or []),
            "estimated_total_time": estimated_total_time,
            "lesson_id": action.get("lesson_id"),
            "resource_id": action.get("resource_id"),
        }


adaptive_learning_loop_service = AdaptiveLearningLoopService()
