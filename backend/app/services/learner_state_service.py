"""Learner-state aggregation for adaptive recommendation policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.app.repositories.recommendation_repository import RecommendationRepository


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
        self.collection = self.repository.db["learner_resource_state"]
        self.snapshot_collection = self.repository.db["learner_state_snapshots"]
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


learner_state_service = LearnerStateService()
