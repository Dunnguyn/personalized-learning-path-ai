"""Learner-state aggregation for adaptive recommendation policies."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Sequence

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.repositories.learning_event_repository import LearningEventRepository
from backend.app.repositories.learning_path_repository import LearningPathRepository
from backend.app.repositories.lesson_repository import LessonRepository
from backend.app.repositories.question_repository import LessonQuestionRepository
from backend.app.repositories.recommendation_repository import RecommendationRepository
from backend.app.repositories.resource_repository import ResourceRepository


@dataclass(frozen=True)
class LearnerState:
    user_id: str
    recent_active_days: int
    avg_session_duration: float
    unfinished_resources: int
    quiz_fail_streak: int
    retry_count: int
    learning_velocity: float
    preferred_time_window: str
    current_focus_concepts: List[str]
    frustration_score: float
    recovery_need_flag: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "recent_active_days": self.recent_active_days,
            "avg_session_duration": self.avg_session_duration,
            "unfinished_resources": self.unfinished_resources,
            "quiz_fail_streak": self.quiz_fail_streak,
            "retry_count": self.retry_count,
            "learning_velocity": self.learning_velocity,
            "preferred_time_window": self.preferred_time_window,
            "current_focus_concepts": list(self.current_focus_concepts),
            "frustration_score": self.frustration_score,
            "recovery_need_flag": self.recovery_need_flag,
        }


class LearnerStateService:
    """Build normalized learner-state features from existing engagement data."""

    def __init__(self, repository: RecommendationRepository | None = None) -> None:
        self.repository = repository or RecommendationRepository()
        self.db = get_db()
        self.collection = self.repository.db["learner_resource_state"]
        self.snapshot_collection = self.repository.db["learner_state_snapshots"]
        self.learning_event_repository = LearningEventRepository()
        self.learning_path_repository = LearningPathRepository()
        self.lesson_repository = LessonRepository()
        self.resource_repository = ResourceRepository()
        self.question_repository = LessonQuestionRepository()
        self.collection.create_index([("user_id", 1)], unique=True)
        self.collection.create_index([("updated_at", -1)])
        self.snapshot_collection.create_index([("user_id", 1), ("snapshot_time", -1)])

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_concept_key(value: Any) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower())
        return normalized.strip("_")

    @staticmethod
    def _extract_payload(event: Dict[str, Any]) -> Dict[str, Any]:
        payload = event.get("payload")
        if isinstance(payload, dict):
            return dict(payload)
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            return dict(metadata)
        return {}

    @staticmethod
    def _safe_bool(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
        return None

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

    def _resolve_lesson_document(self, lesson_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not lesson_id or not self._is_object_id(lesson_id):
            return None
        try:
            return self.lesson_repository.get(lesson_id)
        except Exception:
            return None

    def _resolve_resource_document(self, resource_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not resource_id:
            return None
        try:
            if self._is_object_id(resource_id):
                resource = self.resource_repository.get(resource_id)
                if resource:
                    return resource
        except Exception:
            return None
        return self.resource_repository.collection.find_one({"resource_id": str(resource_id)})

    def _resolve_question_document(self, question_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not question_id:
            return None
        try:
            if self._is_object_id(question_id):
                question = self.question_repository.collection.find_one(
                    {"_id": ObjectId(str(question_id))}
                )
                if question:
                    return question
        except Exception:
            return None
        return self.question_repository.collection.find_one({"question_id": str(question_id)})

    def _resolve_latest_path_id(
        self, user_id: str, lesson_id: Optional[str] = None
    ) -> Optional[str]:
        if lesson_id:
            path = self.learning_path_repository.collection.find_one(
                {
                    "user_id": str(user_id),
                    "$or": [
                        {"chapters.lessons.lesson_id": str(lesson_id)},
                        {"lesson_progress." + str(lesson_id): {"$exists": True}},
                    ],
                },
                sort=[("updated_at", -1), ("created_at", -1)],
            )
            if path:
                return str(path.get("path_id") or "").strip() or None

        latest_event = self.learning_event_repository.latest_one(str(user_id))
        if latest_event and latest_event.get("path_id"):
            return str(latest_event.get("path_id"))

        latest_path = self.learning_path_repository.collection.find_one(
            {"user_id": str(user_id)},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if latest_path:
            return str(latest_path.get("path_id") or "").strip() or None
        return None

    def _resolve_current_lesson_id(
        self,
        *,
        lesson_id: Optional[str],
        events: Sequence[Dict[str, Any]],
    ) -> Optional[str]:
        if lesson_id:
            return str(lesson_id)
        for event in sorted(
            events,
            key=lambda item: self._normalize_datetime(item.get("created_at")),
            reverse=True,
        ):
            candidate = str(event.get("lesson_id") or "").strip()
            if candidate:
                return candidate
        return None

    def _main_concept_from_lesson(self, lesson: Optional[Dict[str, Any]]) -> str:
        if not lesson:
            return ""
        metadata = lesson.get("metadata") or {}
        for candidate in (
            metadata.get("main_concept"),
            metadata.get("concept"),
            lesson.get("concept_id"),
            next(iter(lesson.get("keywords") or []), None),
            next(iter(lesson.get("learning_objectives") or []), None),
            lesson.get("topic"),
            lesson.get("title"),
        ):
            concept_key = self._normalize_concept_key(candidate)
            if concept_key:
                return concept_key
        return ""

    def _resolve_event_concepts(
        self,
        event: Dict[str, Any],
        *,
        lesson: Optional[Dict[str, Any]],
    ) -> List[str]:
        payload = self._extract_payload(event)
        concepts: List[str] = []

        for raw_value in (event.get("concept_ids") or []):
            concept_key = self._normalize_concept_key(raw_value)
            if concept_key:
                concepts.append(concept_key)

        for raw_value in (
            payload.get("concept_ids") or []
            if isinstance(payload.get("concept_ids"), list)
            else []
        ):
            concept_key = self._normalize_concept_key(raw_value)
            if concept_key:
                concepts.append(concept_key)

        for candidate in (payload.get("concept_id"), payload.get("concept")):
            concept_key = self._normalize_concept_key(candidate)
            if concept_key:
                concepts.append(concept_key)

        question = self._resolve_question_document(str(event.get("question_id") or payload.get("question_id") or ""))
        if question:
            for candidate in (
                question.get("concept_id"),
                (question.get("metadata") or {}).get("concept"),
                (question.get("metadata") or {}).get("target_concepts"),
            ):
                if isinstance(candidate, list):
                    for item in candidate:
                        concept_key = self._normalize_concept_key(item)
                        if concept_key:
                            concepts.append(concept_key)
                else:
                    concept_key = self._normalize_concept_key(candidate)
                    if concept_key:
                        concepts.append(concept_key)

        if not concepts:
            fallback = self._main_concept_from_lesson(lesson)
            if fallback:
                concepts.append(fallback)

        deduped: List[str] = []
        seen: set[str] = set()
        for concept in concepts:
            if concept in seen:
                continue
            seen.add(concept)
            deduped.append(concept)
        return deduped

    def _estimate_preferred_resource_type(self, events: Sequence[Dict[str, Any]]) -> Optional[str]:
        counter: Counter[str] = Counter()
        for event in events:
            payload = self._extract_payload(event)
            resource_type = str(payload.get("resource_type") or "").strip().lower()
            if not resource_type and event.get("resource_id"):
                resource = self._resolve_resource_document(str(event.get("resource_id")))
                if resource:
                    resource_type = str(
                        resource.get("type")
                        or resource.get("metadata", {}).get("pedagogy_type")
                        or resource.get("source")
                        or ""
                    ).strip().lower()
            if resource_type:
                counter[resource_type] += 1
        if not counter:
            return None
        return counter.most_common(1)[0][0]

    def _estimate_avg_session_duration(
        self,
        *,
        user_id: str,
        path_id: Optional[str],
        lesson_id: Optional[str],
        events: Sequence[Dict[str, Any]],
    ) -> float:
        durations: List[float] = []
        for event in events:
            payload = self._extract_payload(event)
            for key in ("duration_minutes", "session_duration_minutes"):
                if payload.get(key) is not None:
                    durations.append(self._safe_float(payload.get(key)))
                    break
            else:
                if payload.get("duration_seconds") is not None:
                    durations.append(self._safe_float(payload.get("duration_seconds")) / 60.0)
                elif payload.get("duration_ms") is not None:
                    durations.append(self._safe_float(payload.get("duration_ms")) / 60000.0)

        if not durations:
            study_query: Dict[str, Any] = {"user_id": str(user_id)}
            if path_id:
                study_query["path_id"] = str(path_id)
            if lesson_id:
                study_query["lesson_id"] = str(lesson_id)
            study_rows = list(
                self.db.lesson_study_time.find(
                    study_query,
                    {"seconds_spent": 1},
                ).limit(50)
            )
            durations = [
                self._safe_float(row.get("seconds_spent"), 0.0) / 60.0
                for row in study_rows
                if self._safe_float(row.get("seconds_spent"), 0.0) > 0
            ]

        return round(self._average(durations), 2)

    def _estimate_recent_active_days(self, events: Sequence[Dict[str, Any]]) -> int:
        return len(
            {
                self._normalize_datetime(event.get("created_at")).date().isoformat()
                for event in events
            }
        )

    def _estimate_preferred_time_window(self, events: Sequence[Dict[str, Any]]) -> str:
        buckets = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
        for event in events:
            hour = self._normalize_datetime(event.get("created_at")).hour
            if 5 <= hour < 12:
                buckets["morning"] += 1
            elif 12 <= hour < 17:
                buckets["afternoon"] += 1
            elif 17 <= hour < 22:
                buckets["evening"] += 1
            else:
                buckets["night"] += 1
        return max(buckets.items(), key=lambda item: (item[1], item[0] == "evening"))[0]

    def _estimate_unfinished_resources(self, events: Sequence[Dict[str, Any]]) -> int:
        opened: set[str] = set()
        finished: set[str] = set()
        for event in events:
            resource_id = str(event.get("resource_id") or "").strip()
            if not resource_id:
                continue
            event_type = str(event.get("event_type") or "").strip().lower()
            if event_type in {"resource_viewed", "resource_opened"}:
                opened.add(resource_id)
            if event_type in {"resource_finished", "resource_completed"}:
                finished.add(resource_id)
        return max(len(opened - finished), 0)

    def _estimate_learning_velocity(
        self,
        *,
        active_days: int,
        completion_rate: float,
        events: Sequence[Dict[str, Any]],
    ) -> float:
        completed = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_completed", "resource_finished", "resource_completed"}
        )
        velocity_raw = (completed / max(active_days, 1)) * max(completion_rate, 0.2)
        return round(self._clamp(velocity_raw / 2.0), 4)

    def build_state(self, user_id: str | int) -> Dict[str, Any]:
        normalized_user_id = str(user_id)
        now = self._utcnow()
        cached_snapshot = self.snapshot_collection.find_one(
            {"user_id": normalized_user_id},
            sort=[("is_latest", -1), ("snapshot_time", -1)],
        )
        if cached_snapshot and isinstance(cached_snapshot.get("snapshot_time"), datetime):
            snapshot_age_seconds = (now - cached_snapshot["snapshot_time"].replace(tzinfo=timezone.utc)).total_seconds()
            if snapshot_age_seconds <= 6 * 3600:
                cached_payload = {
                    "user_id": normalized_user_id,
                    "recent_active_days": int(cached_snapshot.get("recent_active_days") or 0),
                    "avg_session_duration": round(self._safe_float(cached_snapshot.get("avg_session_duration"), 12.0), 2),
                    "unfinished_resources": int(cached_snapshot.get("unfinished_resources") or 0),
                    "quiz_fail_streak": int(cached_snapshot.get("quiz_fail_streak") or 0),
                    "retry_count": int(cached_snapshot.get("retry_count") or 0),
                    "learning_velocity": round(self._safe_float(cached_snapshot.get("learning_velocity"), 0.0), 4),
                    "preferred_time_window": str(cached_snapshot.get("preferred_time_window") or "evening"),
                    "current_focus_concepts": list(cached_snapshot.get("current_focus_concepts") or []),
                    "frustration_score": round(self._safe_float(cached_snapshot.get("frustration_score"), 0.0), 4),
                    "recovery_need_flag": bool(cached_snapshot.get("recovery_need_flag")),
                }
                self.collection.update_one(
                    {"user_id": normalized_user_id},
                    {"$set": {**cached_payload, "updated_at": now}},
                    upsert=True,
                )
                return cached_payload

        activity_since = now - timedelta(days=14)
        recent_since = now - timedelta(days=30)

        event_rows = list(
            self.repository.event_logs.find(
                {
                    "user_id": {"$in": self.repository._user_variants(user_id)},
                    "timestamp": {"$gte": activity_since},
                },
                {
                    "timestamp": 1,
                    "event_type": 1,
                    "resource_id": 1,
                    "concept_id": 1,
                    "metadata": 1,
                    "duration_ms": 1,
                },
            )
        )
        study_rows = list(
            self.repository.lesson_study_time.find(
                {
                    "user_id": {"$in": self.repository._user_variants(user_id)},
                    "updated_at": {"$gte": activity_since},
                },
                {"updated_at": 1, "seconds_spent": 1},
            )
        )
        attempt_rows = list(
            self.repository.db["lesson_quiz_attempts"].find(
                {
                    "user_id": normalized_user_id,
                    "submitted_at": {"$gte": recent_since.replace(tzinfo=None)},
                },
                {
                    "lesson_id": 1,
                    "accuracy": 1,
                    "submitted_at": 1,
                    "questions": 1,
                },
            ).sort("submitted_at", -1)
        )
        progress_rows = self.repository.get_user_progress(user_id)

        active_days = set()
        hour_buckets = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
        short_session_count = 0
        session_durations: List[float] = []
        opened_resources: set[str] = set()
        completed_resources: set[str] = set()
        concept_weights: Dict[str, float] = {}

        for row in event_rows:
            timestamp = row.get("timestamp")
            if not isinstance(timestamp, datetime):
                continue
            active_days.add(timestamp.date().isoformat())
            hour = timestamp.hour
            if 5 <= hour < 12:
                hour_buckets["morning"] += 1
            elif 12 <= hour < 17:
                hour_buckets["afternoon"] += 1
            elif 17 <= hour < 22:
                hour_buckets["evening"] += 1
            else:
                hour_buckets["night"] += 1

            duration_minutes = self._safe_float(row.get("duration_ms"), 0.0) / 60000.0
            if duration_minutes > 0:
                session_durations.append(duration_minutes)
                if duration_minutes < 4:
                    short_session_count += 1

            resource_id = row.get("resource_id")
            if resource_id is not None:
                opened_resources.add(str(resource_id))
                if str(row.get("event_type") or "") == "resource_completed":
                    completed_resources.add(str(resource_id))

            concept_id = row.get("concept_id")
            if concept_id is not None:
                concept_key = str(concept_id)
                concept_weights[concept_key] = concept_weights.get(concept_key, 0.0) + 1.0

        for row in study_rows:
            updated_at = row.get("updated_at")
            if isinstance(updated_at, datetime):
                active_days.add(updated_at.date().isoformat())
            duration_minutes = self._safe_float(row.get("seconds_spent"), 0.0) / 60.0
            if duration_minutes > 0:
                session_durations.append(duration_minutes)
                if duration_minutes < 4:
                    short_session_count += 1

        avg_session_duration = round(
            sum(session_durations) / max(len(session_durations), 1), 2
        )
        unfinished_resources = max(len(opened_resources - completed_resources), 0)

        quiz_fail_streak = 0
        retry_count = 0
        attempts_by_lesson: Dict[str, int] = {}
        for row in attempt_rows:
            accuracy = self._safe_float(row.get("accuracy"), 0.0)
            lesson_id = str(row.get("lesson_id") or "")
            if lesson_id:
                attempts_by_lesson[lesson_id] = attempts_by_lesson.get(lesson_id, 0) + 1
            if accuracy < 0.6 and quiz_fail_streak == retry_count // max(len(attempt_rows), 1):
                quiz_fail_streak += 1
            elif quiz_fail_streak > 0 and accuracy >= 0.6:
                break
        retry_count = sum(max(count - 1, 0) for count in attempts_by_lesson.values())

        completed_lessons = self.repository.event_logs.count_documents(
            {
                "user_id": {"$in": self.repository._user_variants(user_id)},
                "timestamp": {"$gte": activity_since},
                "event_type": "lesson_completed",
            }
        )
        completed_resource_events = self.repository.event_logs.count_documents(
            {
                "user_id": {"$in": self.repository._user_variants(user_id)},
                "timestamp": {"$gte": activity_since},
                "event_type": "resource_completed",
            }
        )
        velocity_raw = (completed_lessons + 0.5 * completed_resource_events) / max(
            len(active_days), 1
        )
        learning_velocity = round(self._clamp(velocity_raw / 3.0), 4)

        preferred_time_window = max(
            hour_buckets.items(), key=lambda item: (item[1], item[0] == "evening")
        )[0]

        low_mastery_progress = sorted(
            progress_rows,
            key=lambda item: (
                self._safe_float(item.get("mastery"), 0.0),
                self._safe_float(item.get("confidence"), 0.0),
            ),
        )
        for row in low_mastery_progress[:4]:
            concept_id = row.get("concept_id")
            if concept_id is None:
                continue
            concept_key = str(concept_id)
            concept_weights[concept_key] = concept_weights.get(concept_key, 0.0) + max(
                0.2,
                1.0 - self._safe_float(row.get("mastery"), 0.0),
            )

        concept_ids = [key for key, _ in sorted(concept_weights.items(), key=lambda item: item[1], reverse=True)[:4]]
        concept_docs = (
            list(
                self.repository.concepts.find(
                    {"concept_id": {"$in": [int(item) for item in concept_ids if item.isdigit()]}},
                    {"concept_id": 1, "concept_name": 1},
                )
            )
            if concept_ids
            else []
        )
        concept_name_map = {
            str(doc.get("concept_id")): str(doc.get("concept_name") or str(doc.get("concept_id")))
            for doc in concept_docs
        }
        current_focus_concepts = [
            concept_name_map.get(concept_id, concept_id) for concept_id in concept_ids
        ]

        average_mastery = (
            sum(self._safe_float(item.get("mastery"), 0.0) for item in progress_rows)
            / max(len(progress_rows), 1)
        )
        short_session_ratio = short_session_count / max(len(session_durations), 1)
        unfinished_pressure = unfinished_resources / max(len(opened_resources), 1) if opened_resources else 0.0
        frustration_score = round(
            self._clamp(
                0.32 * self._clamp(quiz_fail_streak / 4.0)
                + 0.18 * self._clamp(retry_count / 6.0)
                + 0.18 * self._clamp(short_session_ratio)
                + 0.14 * self._clamp(unfinished_pressure)
                + 0.18 * self._clamp(1.0 - average_mastery)
            ),
            4,
        )
        recovery_need_flag = bool(
            frustration_score >= 0.58
            and (quiz_fail_streak >= 2 or average_mastery < 0.45)
        )

        payload = LearnerState(
            user_id=normalized_user_id,
            recent_active_days=len(active_days),
            avg_session_duration=avg_session_duration or 12.0,
            unfinished_resources=unfinished_resources,
            quiz_fail_streak=quiz_fail_streak,
            retry_count=retry_count,
            learning_velocity=learning_velocity,
            preferred_time_window=preferred_time_window,
            current_focus_concepts=current_focus_concepts,
            frustration_score=frustration_score,
            recovery_need_flag=recovery_need_flag,
        ).to_dict()

        self.collection.update_one(
            {"user_id": normalized_user_id},
            {"$set": {**payload, "updated_at": now}},
            upsert=True,
        )
        return payload

    def estimate_engagement_score(self, events: Sequence[Dict[str, Any]]) -> float:
        if not events:
            return 0.0

        opened = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {
                "lesson_opened",
                "lesson_started",
                "resource_viewed",
                "resource_opened",
                "quiz_started",
            }
        )
        completed = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {
                "lesson_completed",
                "resource_finished",
                "resource_completed",
                "quiz_submitted",
            }
        )
        abandoned = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_abandoned", "resource_abandoned"}
        )

        duration_values: List[float] = []
        for event in events:
            payload = self._extract_payload(event)
            if payload.get("duration_minutes") is not None:
                duration_values.append(self._safe_float(payload.get("duration_minutes")))
            elif payload.get("duration_seconds") is not None:
                duration_values.append(self._safe_float(payload.get("duration_seconds")) / 60.0)

        completion_signal = completed / max(opened, 1)
        abandonment_penalty = abandoned / max(opened, 1)
        duration_signal = self._clamp(self._average(duration_values) / 15.0)
        engagement = (
            0.55 * self._clamp(completion_signal)
            + 0.25 * duration_signal
            + 0.20 * self._clamp(1.0 - abandonment_penalty)
        )
        return round(self._clamp(engagement), 4)

    def estimate_quiz_accuracy(self, events: Sequence[Dict[str, Any]]) -> float:
        answer_results: List[bool] = []
        submitted_scores: List[float] = []
        for event in events:
            event_type = str(event.get("event_type") or "").strip().lower()
            payload = self._extract_payload(event)
            if event_type == "question_answered":
                answer_state = self._safe_bool(
                    payload.get("is_correct", payload.get("correct"))
                )
                if answer_state is not None:
                    answer_results.append(answer_state)
            elif event_type == "quiz_submitted":
                if payload.get("score") is not None:
                    submitted_scores.append(self._safe_float(payload.get("score")))
                elif payload.get("accuracy") is not None:
                    submitted_scores.append(self._safe_float(payload.get("accuracy")))

        if answer_results:
            correct_answers = sum(1 for item in answer_results if item)
            return round(correct_answers / max(len(answer_results), 1), 4)
        if submitted_scores:
            return round(self._clamp(self._average(submitted_scores)), 4)
        return 0.0

    def estimate_completion_rate(self, events: Sequence[Dict[str, Any]]) -> float:
        viewed = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_opened", "lesson_started", "resource_viewed", "resource_opened"}
        )
        completed = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_completed", "resource_finished", "resource_completed"}
        )
        if viewed <= 0:
            return 1.0 if completed > 0 else 0.0
        return round(self._clamp(completed / viewed), 4)

    def estimate_retry_count(self, events: Sequence[Dict[str, Any]]) -> int:
        return sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"retry_requested", "lesson_retried"}
        )

    def estimate_fail_streak(self, events: Sequence[Dict[str, Any]]) -> int:
        streak = 0
        ordered = sorted(
            events,
            key=lambda item: self._normalize_datetime(item.get("created_at")),
            reverse=True,
        )
        for event in ordered:
            event_type = str(event.get("event_type") or "").strip().lower()
            payload = self._extract_payload(event)
            if event_type == "question_answered":
                answer_state = self._safe_bool(
                    payload.get("is_correct", payload.get("correct"))
                )
                if answer_state is None:
                    continue
                if answer_state is False:
                    streak += 1
                    continue
                break
            if event_type == "quiz_submitted":
                score = payload.get("score", payload.get("accuracy"))
                if score is None:
                    continue
                if self._safe_float(score) < 0.5:
                    streak += 1
                    continue
                break
        return streak

    def estimate_fatigue_score(self, events: Sequence[Dict[str, Any]]) -> float:
        opened = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_opened", "lesson_started", "resource_viewed", "resource_opened"}
        )
        completed = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_completed", "resource_finished", "resource_completed"}
        )
        abandoned = sum(
            1
            for event in events
            if str(event.get("event_type") or "").strip().lower()
            in {"lesson_abandoned", "resource_abandoned"}
        )
        retry_count = self.estimate_retry_count(events)
        fail_streak = self.estimate_fail_streak(events)
        imbalance = (abandoned + max(opened - completed, 0)) / max(opened, 1)
        fatigue = (
            0.35 * self._clamp(retry_count / 5.0)
            + 0.35 * self._clamp(fail_streak / 4.0)
            + 0.30 * self._clamp(imbalance)
        )
        return round(self._clamp(fatigue), 4)

    def estimate_mastery_by_concept(
        self,
        user_id: str,
        path_id: Optional[str],
        lesson_id: Optional[str],
        events: Sequence[Dict[str, Any]],
    ) -> Dict[str, float]:
        del user_id, path_id

        lesson = self._resolve_lesson_document(lesson_id)
        overall_accuracy = self.estimate_quiz_accuracy(events)
        overall_completion = self.estimate_completion_rate(events)
        overall_retry_count = self.estimate_retry_count(events)

        stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "answers": 0,
                "correct": 0,
                "viewed": 0,
                "completed": 0,
                "retries": 0,
                "last_seen": None,
            }
        )

        for event in events:
            event_type = str(event.get("event_type") or "").strip().lower()
            payload = self._extract_payload(event)
            concepts = self._resolve_event_concepts(event, lesson=lesson)
            if not concepts:
                continue

            for concept in concepts:
                bucket = stats[concept]
                bucket["last_seen"] = self._normalize_datetime(event.get("created_at"))

                if event_type in {"lesson_opened", "lesson_started", "resource_viewed", "resource_opened"}:
                    bucket["viewed"] += 1
                if event_type in {"lesson_completed", "resource_finished", "resource_completed"}:
                    bucket["completed"] += 1
                if event_type in {"retry_requested", "lesson_retried"}:
                    bucket["retries"] += 1
                if event_type == "question_answered":
                    answer_state = self._safe_bool(
                        payload.get("is_correct", payload.get("correct"))
                    )
                    if answer_state is not None:
                        bucket["answers"] += 1
                        bucket["correct"] += int(answer_state)
                elif event_type == "quiz_submitted":
                    score = payload.get("score", payload.get("accuracy"))
                    question_count = int(payload.get("question_count") or payload.get("total_questions") or 1)
                    score_value = self._safe_float(score, default=overall_accuracy)
                    bucket["answers"] += max(question_count, 1)
                    bucket["correct"] += int(round(score_value * max(question_count, 1)))

        if not stats:
            fallback_concept = self._main_concept_from_lesson(lesson)
            if fallback_concept:
                stats[fallback_concept] = {
                    "answers": 0,
                    "correct": 0,
                    "viewed": 1 if events else 0,
                    "completed": 1
                    if any(
                        str(event.get("event_type") or "").strip().lower() == "lesson_completed"
                        for event in events
                    )
                    else 0,
                    "retries": overall_retry_count,
                    "last_seen": self._normalize_datetime(events[-1].get("created_at")) if events else self._utcnow(),
                }

        now = self._utcnow()
        mastery_by_concept: Dict[str, float] = {}
        for concept, bucket in stats.items():
            accuracy = (
                bucket["correct"] / max(bucket["answers"], 1)
                if bucket["answers"] > 0
                else overall_accuracy
            )
            completion = (
                bucket["completed"] / max(bucket["viewed"], 1)
                if bucket["viewed"] > 0
                else overall_completion
            )
            last_seen = bucket.get("last_seen") or now
            days_since = max(
                (now - self._normalize_datetime(last_seen)).total_seconds() / 86400.0,
                0.0,
            )
            recency_bonus = 1.0 if days_since <= 3 else 0.7 if days_since <= 7 else 0.4
            retry_inverse = 1.0 / (1.0 + max(int(bucket.get("retries") or 0), overall_retry_count))
            mastery = (
                0.6 * self._clamp(accuracy)
                + 0.2 * self._clamp(completion)
                + 0.1 * self._clamp(recency_bonus)
                + 0.1 * self._clamp(retry_inverse)
            )
            mastery_by_concept[concept] = round(self._clamp(mastery), 4)
        return mastery_by_concept

    def compute_snapshot(
        self,
        user_id: str,
        path_id: Optional[str],
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_user_id = str(user_id)
        resolved_path_id = str(path_id or self._resolve_latest_path_id(normalized_user_id, lesson_id) or "").strip() or None
        events = self.learning_event_repository.list_recent(
            user_id=normalized_user_id,
            path_id=resolved_path_id,
            lesson_id=lesson_id,
            limit=1000,
        )
        events = sorted(
            events,
            key=lambda item: self._normalize_datetime(item.get("created_at")),
        )
        current_lesson_id = self._resolve_current_lesson_id(
            lesson_id=lesson_id,
            events=events,
        )

        mastery_by_concept = self.estimate_mastery_by_concept(
            normalized_user_id,
            resolved_path_id,
            current_lesson_id,
            events,
        )
        engagement_score = self.estimate_engagement_score(events)
        quiz_accuracy = self.estimate_quiz_accuracy(events)
        completion_rate = self.estimate_completion_rate(events)
        retry_count = self.estimate_retry_count(events)
        fail_streak = self.estimate_fail_streak(events)
        fatigue_score = self.estimate_fatigue_score(events)
        avg_session_duration = self._estimate_avg_session_duration(
            user_id=normalized_user_id,
            path_id=resolved_path_id,
            lesson_id=current_lesson_id,
            events=events,
        )
        preferred_resource_type = self._estimate_preferred_resource_type(events)
        unfinished_resources = self._estimate_unfinished_resources(events)
        recent_active_days = self._estimate_recent_active_days(events)
        learning_velocity = self._estimate_learning_velocity(
            active_days=recent_active_days,
            completion_rate=completion_rate,
            events=events,
        )

        weakest_concepts = [
            concept
            for concept, _ in sorted(
                mastery_by_concept.items(),
                key=lambda item: item[1],
            )[:3]
        ]

        risk_score = max(
            fatigue_score,
            1.0 - self._clamp(quiz_accuracy),
            1.0 - self._clamp(completion_rate),
        )
        if risk_score >= 0.75:
            risk_level = "high"
        elif risk_score >= 0.45:
            risk_level = "medium"
        else:
            risk_level = "low"

        updated_at = self._utcnow()
        snapshot = {
            "snapshot_id": f"snapshot_{ObjectId()}",
            "user_id": normalized_user_id,
            "path_id": resolved_path_id,
            "current_lesson_id": current_lesson_id,
            "mastery_by_concept": mastery_by_concept,
            "confidence_by_concept": dict(mastery_by_concept),
            "engagement_score": round(engagement_score, 4),
            "quiz_accuracy": round(quiz_accuracy, 4),
            "completion_rate": round(completion_rate, 4),
            "avg_session_duration": round(avg_session_duration, 2),
            "retry_count": retry_count,
            "fail_streak": fail_streak,
            "fatigue_score": round(fatigue_score, 4),
            "risk_level": risk_level,
            "preferred_resource_type": preferred_resource_type,
            "updated_at": updated_at,
            "snapshot_time": updated_at,
            "unfinished_resources": unfinished_resources,
            "quiz_fail_streak": fail_streak,
            "learning_velocity": learning_velocity,
            "current_focus_concepts": weakest_concepts,
            "needs_reinforcement": bool(risk_level != "low"),
            "last_event_type": str(events[-1].get("event_type") or "") if events else None,
            "recent_active_days": recent_active_days,
            "preferred_time_window": self._estimate_preferred_time_window(events) if events else "evening",
            "frustration_score": round(fatigue_score, 4),
            "recovery_need_flag": bool(risk_level == "high"),
        }
        return snapshot


learner_state_service = LearnerStateService()
