"""Repository methods for analytics aggregation from canonicalized domain data."""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId

from backend.app.services.analytics_contract import (
    analytics_metadata,
    canonical_event_name,
    equivalent_event_names,
)


class AnalyticsRepository:
    """Aggregate learner/admin analytics from canonical collections with legacy fallback."""

    def __init__(self, db):
        self.db = db
        self.event_logs = db.event_logs
        self.learning_events = db["learning_events"]
        self.progress = db.progress
        self.learning_paths = db.learning_paths
        self.exercise_attempts = db.exercise_attempts
        self.adaptive_attempts = db["lesson_quiz_attempts"]
        self.lesson_study_time = db["lesson_study_time"]
        self.users = db.users
        self.learner_state_snapshots = db["learner_state_snapshots"]
        self.ask_history = db["ask_history"]
        self.path_refinement_actions = db["path_refinement_actions"]
        self.intervention_logs = db["intervention_logs"]
        self.resources = db["resources"]

    @staticmethod
    def _to_date_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _max_timestamp(*timestamps: datetime | None) -> datetime | None:
        valid_timestamps = [
            AnalyticsRepository._normalize_datetime(item)
            for item in timestamps
            if isinstance(item, datetime)
        ]
        valid_timestamps = [item for item in valid_timestamps if isinstance(item, datetime)]
        return max(valid_timestamps) if valid_timestamps else None

    @staticmethod
    def _normalize_datetime(value: Any) -> Optional[datetime]:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _event_metadata(document: Dict[str, Any]) -> Dict[str, Any]:
        metadata = document.get("metadata")
        if isinstance(metadata, dict):
            return dict(metadata)
        payload = document.get("payload")
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    def _event_timestamp(self, document: Dict[str, Any]) -> Optional[datetime]:
        return self._normalize_datetime(
            document.get("timestamp") or document.get("created_at")
        )

    def _event_session_id(self, document: Dict[str, Any]) -> Optional[str]:
        metadata = self._event_metadata(document)
        raw_value = (
            document.get("session_id")
            or metadata.get("session_id")
            or metadata.get("session")
        )
        text = str(raw_value or "").strip()
        return text or None

    def _event_fingerprint(self, document: Dict[str, Any]) -> tuple[str, ...]:
        timestamp = self._event_timestamp(document)
        metadata = self._event_metadata(document)
        score = metadata.get("score", metadata.get("accuracy"))
        return (
            str(document.get("user_id") or "").strip(),
            canonical_event_name(str(document.get("event_type") or "")),
            str(document.get("path_id") or "").strip(),
            str(document.get("lesson_id") or "").strip(),
            str(document.get("resource_id") or "").strip(),
            str(document.get("question_id") or metadata.get("question_id") or "").strip(),
            (
                timestamp.replace(microsecond=0).isoformat()
                if isinstance(timestamp, datetime)
                else ""
            ),
            str(score if score is not None else ""),
        )

    @staticmethod
    def _find_many(collection, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        if projection is None:
            return list(collection.find(query))
        return list(collection.find(query, projection))

    def _combined_events(
        self,
        *,
        user_id: Optional[str] = None,
        since: Optional[datetime] = None,
        event_names: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        log_query: Dict[str, Any] = {}
        learning_query: Dict[str, Any] = {}

        if user_id is not None:
            log_query["user_id"] = str(user_id)
            learning_query["user_id"] = str(user_id)
        if since is not None:
            log_query["timestamp"] = {"$gte": since}
            learning_query["created_at"] = {"$gte": since.replace(tzinfo=None)}
        if event_names:
            normalized_names = equivalent_event_names(*list(event_names))
            log_query["event_type"] = {"$in": normalized_names}
            learning_query["event_type"] = {"$in": normalized_names}

        projection = {
            "event_id": 1,
            "event_type": 1,
            "timestamp": 1,
            "created_at": 1,
            "user_id": 1,
            "session_id": 1,
            "path_id": 1,
            "lesson_id": 1,
            "resource_id": 1,
            "question_id": 1,
            "metadata": 1,
            "payload": 1,
            "success": 1,
            "duration_ms": 1,
            "latency_ms": 1,
            "cost_estimate": 1,
            "error_code": 1,
        }

        rows = self._find_many(self.event_logs, log_query, projection)
        rows.extend(self._find_many(self.learning_events, learning_query, projection))

        deduped: Dict[tuple[str, ...], Dict[str, Any]] = {}
        for row in rows:
            timestamp = self._event_timestamp(row)
            if since is not None and timestamp is not None and timestamp < since:
                continue

            normalized = dict(row)
            normalized["event_type"] = canonical_event_name(
                str(normalized.get("event_type") or "")
            )
            normalized["_event_time"] = timestamp

            fingerprint = self._event_fingerprint(normalized)
            current = deduped.get(fingerprint)
            if current is None:
                deduped[fingerprint] = normalized
                continue

            current_time = current.get("_event_time")
            if isinstance(timestamp, datetime) and (
                not isinstance(current_time, datetime) or timestamp > current_time
            ):
                deduped[fingerprint] = normalized

        return sorted(
            deduped.values(),
            key=lambda item: item.get("_event_time") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _normalize_attempt_timestamp(value: Any) -> Optional[datetime]:
        if not isinstance(value, datetime):
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def _legacy_attempt_payload(self, document: Dict[str, Any]) -> Dict[str, Any]:
        questions = list(document.get("questions") or [])
        question_count = len(questions)
        correct_count = sum(1 for item in questions if bool(item.get("is_correct")))
        accuracy = (
            (correct_count / question_count)
            if question_count
            else float(document.get("confidence", 0.0) or 0.0)
        )
        return {
            "attempt_id": str(document.get("_id") or ""),
            "user_id": str(document.get("user_id") or ""),
            "path_id": str(document.get("path_id") or ""),
            "lesson_id": str(document.get("lesson_id") or ""),
            "submitted_at": self._normalize_attempt_timestamp(document.get("created_at")),
            "question_count": question_count,
            "correct_count": correct_count,
            "accuracy": float(accuracy or 0.0),
            "source": "exercise_attempts",
        }

    def _adaptive_attempt_payload(self, document: Dict[str, Any]) -> Dict[str, Any]:
        question_count = int(
            document.get("total_questions")
            or len(document.get("questions") or [])
            or 0
        )
        accuracy = float(document.get("accuracy", 0.0) or 0.0)
        correct_count = int(
            document.get("correct_count")
            or round(accuracy * max(question_count, 0))
        )
        return {
            "attempt_id": str(document.get("attempt_id") or document.get("_id") or ""),
            "user_id": str(document.get("user_id") or ""),
            "path_id": str(document.get("path_id") or ""),
            "lesson_id": str(document.get("lesson_id") or ""),
            "submitted_at": self._normalize_attempt_timestamp(document.get("submitted_at")),
            "question_count": question_count,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "source": "lesson_quiz_attempts",
        }

    def _combined_attempts(self, user_id: str) -> List[Dict[str, Any]]:
        normalized_user_id = str(user_id)
        attempts: List[Dict[str, Any]] = []
        attempts.extend(
            self._legacy_attempt_payload(item)
            for item in self._find_many(
                self.exercise_attempts,
                {"user_id": normalized_user_id},
                {"user_id": 1, "path_id": 1, "lesson_id": 1, "created_at": 1, "questions": 1, "confidence": 1},
            )
        )
        attempts.extend(
            self._adaptive_attempt_payload(item)
            for item in self._find_many(
                self.adaptive_attempts,
                {"user_id": normalized_user_id},
                {
                    "attempt_id": 1,
                    "user_id": 1,
                    "path_id": 1,
                    "lesson_id": 1,
                    "submitted_at": 1,
                    "total_questions": 1,
                    "correct_count": 1,
                    "accuracy": 1,
                    "questions": 1,
                },
            )
        )

        deduped: Dict[tuple[str, ...], Dict[str, Any]] = {}
        for item in attempts:
            submitted_at = item.get("submitted_at")
            fingerprint = (
                str(item.get("attempt_id") or ""),
                str(item.get("lesson_id") or ""),
                str(item.get("path_id") or ""),
                (
                    submitted_at.replace(microsecond=0).isoformat()
                    if isinstance(submitted_at, datetime)
                    else ""
                ),
                str(item.get("question_count") or 0),
                str(item.get("correct_count") or 0),
            )
            existing = deduped.get(fingerprint)
            if existing is None:
                deduped[fingerprint] = item
                continue
            if item.get("source") == "lesson_quiz_attempts":
                deduped[fingerprint] = item

        return sorted(
            deduped.values(),
            key=lambda item: item.get("submitted_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _status(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"completed", "complete"}:
            return "completed"
        if normalized == "in_progress":
            return "in_progress"
        return "not_started"

    def _average_snapshot_confidence(self, snapshot: Dict[str, Any]) -> float:
        confidence_map = snapshot.get("confidence_by_concept") or {}
        if isinstance(confidence_map, dict) and confidence_map:
            values = [
                self._safe_float(item, 0.0)
                for item in confidence_map.values()
                if item is not None
            ]
            if values:
                return sum(values) / len(values)
        return self._safe_float(snapshot.get("quiz_accuracy"), 0.0)

    def _snapshot_histories(
        self,
        *,
        user_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        query: Dict[str, Any] = {}
        normalized_user_ids = [str(item) for item in (user_ids or []) if str(item).strip()]
        if normalized_user_ids:
            query["user_id"] = {"$in": normalized_user_ids}

        rows = list(
            self.learner_state_snapshots.find(
                query,
                {
                    "user_id": 1,
                    "snapshot_time": 1,
                    "updated_at": 1,
                    "confidence_by_concept": 1,
                    "quiz_accuracy": 1,
                },
            ).sort([("user_id", 1), ("snapshot_time", 1), ("updated_at", 1)])
        )

        histories: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            user_id = str(row.get("user_id") or "").strip()
            if not user_id:
                continue
            snapshot_time = self._normalize_datetime(
                row.get("snapshot_time") or row.get("updated_at")
            )
            if not isinstance(snapshot_time, datetime):
                continue
            histories.setdefault(user_id, []).append(
                {
                    "timestamp": snapshot_time,
                    "avg_confidence": round(
                        self._average_snapshot_confidence(row),
                        4,
                    ),
                }
            )
        return histories

    @staticmethod
    def _snapshot_confidence_delta(
        history: List[Dict[str, Any]],
        event_time: datetime,
        *,
        lookback_hours: int = 72,
        lookahead_hours: int = 72,
    ) -> Optional[float]:
        if not history:
            return None

        timestamps = [
            item["timestamp"]
            for item in history
            if isinstance(item.get("timestamp"), datetime)
        ]
        if not timestamps:
            return None

        index = bisect_left(timestamps, event_time)
        previous_index = index - 1
        next_index = index

        previous_snapshot = history[previous_index] if previous_index >= 0 else None
        next_snapshot = history[next_index] if next_index < len(history) else None
        if not previous_snapshot or not next_snapshot:
            return None

        previous_time = previous_snapshot.get("timestamp")
        next_time = next_snapshot.get("timestamp")
        if not isinstance(previous_time, datetime) or not isinstance(next_time, datetime):
            return None

        if previous_time < event_time - timedelta(hours=lookback_hours):
            return None
        if next_time > event_time + timedelta(hours=lookahead_hours):
            return None

        return round(
            float(next_snapshot.get("avg_confidence", 0.0) or 0.0)
            - float(previous_snapshot.get("avg_confidence", 0.0) or 0.0),
            4,
        )

    def learner_completion_stats(self, user_id: str) -> Dict[str, Any]:
        paths = list(self.learning_paths.find({"user_id": user_id}))
        total_lessons = 0
        completed_lessons = 0
        in_progress_lessons = 0
        for path in paths:
            lesson_progress = path.get("lesson_progress", {}) or {}
            total_lessons += len(lesson_progress)
            completed_lessons += sum(
                1 for status in lesson_progress.values() if self._status(status) == "completed"
            )
            in_progress_lessons += sum(
                1 for status in lesson_progress.values() if self._status(status) == "in_progress"
            )

        completion_rate = (completed_lessons / total_lessons) if total_lessons else 0.0
        dropout_rate = (
            ((total_lessons - completed_lessons) / total_lessons)
            if total_lessons
            else 0.0
        )
        return {
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "in_progress_lessons": in_progress_lessons,
            "completion_rate": round(completion_rate, 4),
            "dropout_rate": round(dropout_rate, 4),
        }

    def learner_mastery_confidence_gain(self, user_id: str) -> Dict[str, Any]:
        rows = list(
            self.progress.find({"user_id": user_id}).sort(
                [("concept_id", 1), ("last_updated", 1)]
            )
        )
        if not rows:
            return {
                "mastery_gain": 0.0,
                "confidence_gain": 0.0,
                "overall_mastery": 0.0,
                "overall_confidence": 0.0,
            }

        by_concept: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            by_concept.setdefault(int(row.get("concept_id", 0)), []).append(row)

        mastery_gain = 0.0
        confidence_gain = 0.0
        latest_rows: List[Dict[str, Any]] = []
        for history in by_concept.values():
            first = history[0]
            last = history[-1]
            mastery_gain += float(last.get("mastery", 0.0) or 0.0) - float(
                first.get("mastery", 0.0) or 0.0
            )
            confidence_gain += float(last.get("confidence", 0.0) or 0.0) - float(
                first.get("confidence", 0.0) or 0.0
            )
            latest_rows.append(last)

        overall_mastery = sum(
            float(r.get("mastery", 0.0) or 0.0) for r in latest_rows
        ) / len(latest_rows)
        overall_confidence = sum(
            float(r.get("confidence", 0.0) or 0.0) for r in latest_rows
        ) / len(latest_rows)

        return {
            "mastery_gain": round(mastery_gain, 4),
            "confidence_gain": round(confidence_gain, 4),
            "overall_mastery": round(overall_mastery, 4),
            "overall_confidence": round(overall_confidence, 4),
        }

    def learner_time_and_streak(self, user_id: str) -> Dict[str, Any]:
        time_per_lesson: Dict[str, int] = {}
        for item in self.lesson_study_time.find(
            {"user_id": user_id},
            {"lesson_id": 1, "seconds_spent": 1},
        ):
            lesson_id = str(item.get("lesson_id") or "").strip()
            if not lesson_id:
                continue
            time_per_lesson[lesson_id] = time_per_lesson.get(lesson_id, 0) + int(
                item.get("seconds_spent", 0) or 0
            )

        now = datetime.now(timezone.utc)
        recent_events = self._combined_events(
            user_id=user_id,
            since=now - timedelta(days=30),
            event_names=(
                "lesson_opened",
                "lesson_completed",
                "quiz_submitted",
                "resource_clicked",
                "resource_viewed",
                "resource_completed",
            ),
        )

        active_days = sorted(
            {
                self._to_date_key(item["_event_time"])
                for item in recent_events
                if isinstance(item.get("_event_time"), datetime)
            }
        )
        streak = 0
        cursor_day = now.date()
        active_set = set(active_days)
        while cursor_day.strftime("%Y-%m-%d") in active_set:
            streak += 1
            cursor_day = cursor_day - timedelta(days=1)

        session_events = self._combined_events(user_id=user_id)
        session_ranges: Dict[str, List[datetime]] = {}
        for event in session_events:
            session_id = self._event_session_id(event)
            ts = event.get("_event_time")
            if not session_id or not isinstance(ts, datetime):
                continue
            session_ranges.setdefault(session_id, []).append(ts)

        session_lengths_ms = []
        for timestamps in session_ranges.values():
            session_lengths_ms.append(
                int((max(timestamps) - min(timestamps)).total_seconds() * 1000)
            )

        avg_session_ms = (
            (sum(session_lengths_ms) / len(session_lengths_ms))
            if session_lengths_ms
            else 0.0
        )

        return {
            "time_spent_per_lesson": time_per_lesson,
            "learning_streak_days": streak,
            "session_length_ms_avg": int(avg_session_ms),
        }

    def learner_recommendation_and_quiz_stats(self, user_id: str) -> Dict[str, Any]:
        events = self._combined_events(
            user_id=user_id,
            event_names=(
                "recommendation_shown",
                "recommendation_clicked",
                "resource_clicked",
                "resource_completed",
            ),
        )
        shown = sum(1 for item in events if item.get("event_type") == "recommendation_shown")
        clicked = sum(
            1 for item in events if item.get("event_type") == "recommendation_clicked"
        )
        resource_click = sum(
            1 for item in events if item.get("event_type") == "resource_clicked"
        )
        resource_done = sum(
            1 for item in events if item.get("event_type") == "resource_completed"
        )

        attempts = self._combined_attempts(user_id)
        total_questions = 0
        total_correct = 0
        by_lesson: Dict[str, int] = {}
        for attempt in attempts:
            lesson_id = str(attempt.get("lesson_id") or "")
            by_lesson[lesson_id] = by_lesson.get(lesson_id, 0) + 1
            total_questions += int(attempt.get("question_count") or 0)
            total_correct += int(attempt.get("correct_count") or 0)

        retry_attempts = sum(max(count - 1, 0) for count in by_lesson.values())
        retry_rate = (retry_attempts / len(attempts)) if attempts else 0.0
        quiz_accuracy = (total_correct / total_questions) if total_questions else 0.0
        recommendation_ctr = (min(clicked, shown) / shown) if shown else 0.0
        resource_completion_after_click = (
            (min(resource_done, resource_click) / resource_click)
            if resource_click
            else 0.0
        )

        return {
            "recommendation_ctr": round(recommendation_ctr, 4),
            "resource_completion_after_click": round(
                resource_completion_after_click, 4
            ),
            "quiz_accuracy": round(quiz_accuracy, 4),
            "retry_rate": round(retry_rate, 4),
            "quiz_attempts": len(attempts),
        }

    def learner_state_overview(self, user_id: str) -> Dict[str, Any]:
        snapshot = self.learner_state_snapshots.find_one(
            {"user_id": str(user_id)},
            sort=[("is_latest", -1), ("updated_at", -1), ("snapshot_time", -1)],
        )
        if not snapshot:
            return {}
        return {
            "risk_level": str(snapshot.get("risk_level") or "low"),
            "engagement_score": round(float(snapshot.get("engagement_score", 0.0) or 0.0), 4),
            "quiz_accuracy": round(float(snapshot.get("quiz_accuracy", 0.0) or 0.0), 4),
            "completion_rate": round(float(snapshot.get("completion_rate", 0.0) or 0.0), 4),
            "current_focus_concepts": list(snapshot.get("current_focus_concepts") or []),
            "updated_at": snapshot.get("updated_at") or snapshot.get("snapshot_time"),
        }

    def admin_overview(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        daily_events = self._combined_events(since=day_ago)
        weekly_events = self._combined_events(since=week_ago)

        dau = len(
            {
                str(item.get("user_id") or "").strip()
                for item in daily_events
                if str(item.get("user_id") or "").strip()
            }
        )
        wau = len(
            {
                str(item.get("user_id") or "").strip()
                for item in weekly_events
                if str(item.get("user_id") or "").strip()
            }
        )

        learning_path_events = self._combined_events(event_names=("learning_path_generated",))
        lp_total = len(learning_path_events)
        lp_success = sum(1 for item in learning_path_events if bool(item.get("success")))

        return {
            "dau": dau,
            "wau": wau,
            "learning_path_generation_success_rate": round(
                (lp_success / lp_total) if lp_total else 0.0, 4
            ),
        }

    def system_performance_overview(self) -> Dict[str, Any]:
        api_events = list(
            self.event_logs.find(
                {"event_type": {"$in": equivalent_event_names("api_called", "api_failed")}},
                {
                    "duration_ms": 1,
                    "event_type": 1,
                    "latency_ms": 1,
                    "cost_estimate": 1,
                },
            )
        )
        latency = sorted(
            [
                int(item.get("duration_ms") or item.get("latency_ms") or 0)
                for item in api_events
                if int(item.get("duration_ms") or item.get("latency_ms") or 0) > 0
            ]
        )
        total_calls = len(api_events)
        failed_calls = sum(
            1
            for item in api_events
            if canonical_event_name(str(item.get("event_type") or "")) == "api_failed"
        )

        def percentile(values: List[int], p: float) -> float:
            if not values:
                return 0.0
            idx = int((len(values) - 1) * p)
            return float(values[idx])

        llm_calls = list(
            self.event_logs.find(
                {"event_type": {"$in": equivalent_event_names("llm_called")}},
                {"cost_estimate": 1},
            )
        )
        total_cost = sum(
            float(item.get("cost_estimate", 0.0) or 0.0) for item in llm_calls
        )

        return {
            "p50_latency_ms": percentile(latency, 0.50),
            "p95_latency_ms": percentile(latency, 0.95),
            "p99_latency_ms": percentile(latency, 0.99),
            "api_error_rate": round(
                (failed_calls / total_calls) if total_calls else 0.0, 4
            ),
            "total_api_calls": total_calls,
            "failed_api_calls": failed_calls,
            "ai_request_cost_estimate": round(total_cost, 6),
        }

    def average_study_hours_overview(self) -> Dict[str, Any]:
        total_users = self.users.count_documents({})
        total_study_seconds = 0
        for item in self.lesson_study_time.find({}, {"seconds_spent": 1}):
            total_study_seconds += int(item.get("seconds_spent", 0) or 0)

        total_study_hours = total_study_seconds / 3600 if total_study_seconds else 0.0
        average_study_hours = (
            total_study_hours / total_users if total_users else 0.0
        )

        return {
            "average_study_hours_per_user": round(average_study_hours, 2),
            "total_study_hours": round(total_study_hours, 2),
            "user_count": total_users,
        }

    def admin_dashboard(self) -> Dict[str, Any]:
        overview = self.admin_overview()
        performance = self.system_performance_overview()
        study_hours = self.average_study_hours_overview()
        lp_total = len(self._combined_events(event_names=("learning_path_generated",)))
        user_event_count = len(self._combined_events())
        has_user_data = bool(
            study_hours["user_count"] > 0
            or study_hours["total_study_hours"] > 0
            or lp_total > 0
            or user_event_count > 0
        )

        latest_event = self.event_logs.find_one(
            {"user_id": {"$ne": None}},
            {"timestamp": 1},
            sort=[("timestamp", -1)],
        )
        latest_learning_event = self.learning_events.find_one(
            {"user_id": {"$ne": None}},
            {"created_at": 1},
            sort=[("created_at", -1)],
        )
        latest_study_time = self.lesson_study_time.find_one(
            {}, {"updated_at": 1}, sort=[("updated_at", -1)]
        )
        latest_user = self.users.find_one(
            {},
            {"updated_at": 1, "created_at": 1},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        updated_at = self._max_timestamp(
            self._normalize_datetime(latest_event.get("timestamp")) if latest_event else None,
            self._normalize_datetime(latest_learning_event.get("created_at"))
            if latest_learning_event
            else None,
            latest_study_time.get("updated_at") if latest_study_time else None,
            (
                latest_user.get("updated_at") or latest_user.get("created_at")
                if latest_user
                else None
            ),
        )

        return {
            "dau": overview["dau"],
            "wau": overview["wau"],
            "learning_path_generation_success_rate": overview[
                "learning_path_generation_success_rate"
            ],
            "average_study_hours_per_user": study_hours[
                "average_study_hours_per_user"
            ],
            "total_study_hours": study_hours["total_study_hours"],
            "user_count": study_hours["user_count"],
            "p50_latency_ms": performance["p50_latency_ms"],
            "p95_latency_ms": performance["p95_latency_ms"],
            "p99_latency_ms": performance["p99_latency_ms"],
            "api_error_rate": performance["api_error_rate"],
            "has_user_data": has_user_data,
            "no_data_message": (
                None
                if has_user_data
                else "Chưa có dữ liệu người dùng hoặc dữ liệu học tập để hiển thị."
            ),
            "updated_at": updated_at,
            "analytics_schema_version": "analytics.v1",
            "source_of_truth": analytics_metadata(),
        }

    def research_recommendation_metrics(self, *, days: int = 30) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=max(1, days))
        events = self._combined_events(
            since=since,
            event_names=(
                "recommendation_shown",
                "recommendation_clicked",
                "resource_clicked",
                "resource_completed",
            ),
        )
        shown_events = [
            item for item in events if item.get("event_type") == "recommendation_shown"
        ]
        clicked_events = [
            item for item in events if item.get("event_type") == "recommendation_clicked"
        ]
        completion_events = [
            item for item in events if item.get("event_type") == "resource_completed"
        ]

        completion_lookup: Dict[tuple[str, str], List[datetime]] = {}
        for item in completion_events:
            user_id = str(item.get("user_id") or "").strip()
            resource_id = str(item.get("resource_id") or "").strip()
            event_time = item.get("_event_time")
            if not user_id or not resource_id or not isinstance(event_time, datetime):
                continue
            completion_lookup.setdefault((user_id, resource_id), []).append(event_time)
        for timestamps in completion_lookup.values():
            timestamps.sort()

        user_histories = self._snapshot_histories(
            user_ids={
                str(item.get("user_id") or "").strip()
                for item in clicked_events
                if str(item.get("user_id") or "").strip()
            }
        )

        top_resource_metrics: Dict[str, Dict[str, Any]] = {}
        completion_after_click = 0
        confidence_deltas: List[float] = []

        for event in shown_events:
            resource_id = str(event.get("resource_id") or "").strip()
            if not resource_id:
                continue
            metric = top_resource_metrics.setdefault(
                resource_id,
                {
                    "resource_id": resource_id,
                    "shown": 0,
                    "clicked": 0,
                    "completed_after_click": 0,
                },
            )
            metric["shown"] += 1

        for event in clicked_events:
            user_id = str(event.get("user_id") or "").strip()
            resource_id = str(event.get("resource_id") or "").strip()
            event_time = event.get("_event_time")
            if not resource_id:
                continue

            metric = top_resource_metrics.setdefault(
                resource_id,
                {
                    "resource_id": resource_id,
                    "shown": 0,
                    "clicked": 0,
                    "completed_after_click": 0,
                },
            )
            metric["clicked"] += 1

            if user_id and isinstance(event_time, datetime):
                completions = completion_lookup.get((user_id, resource_id), [])
                if any(
                    item >= event_time and item <= event_time + timedelta(days=7)
                    for item in completions
                ):
                    completion_after_click += 1
                    metric["completed_after_click"] += 1

                history = user_histories.get(user_id) or []
                delta = self._snapshot_confidence_delta(history, event_time)
                if delta is not None:
                    confidence_deltas.append(delta)

        resource_titles: Dict[str, str] = {}
        resource_object_ids = []
        for resource_id in top_resource_metrics.keys():
            if ObjectId.is_valid(resource_id):
                resource_object_ids.append(ObjectId(resource_id))
        if resource_object_ids:
            resource_titles.update(
                {
                    str(item.get("_id")): str(
                        item.get("title") or item.get("topic") or "Untitled resource"
                    )
                    for item in self.resources.find(
                        {"_id": {"$in": resource_object_ids}},
                        {"title": 1, "topic": 1},
                    )
                }
            )

        top_resources = []
        for resource_id, metric in top_resource_metrics.items():
            shown = int(metric.get("shown") or 0)
            clicked = int(metric.get("clicked") or 0)
            completed = int(metric.get("completed_after_click") or 0)
            top_resources.append(
                {
                    "resource_id": resource_id,
                    "title": resource_titles.get(resource_id, f"Resource {resource_id}"),
                    "shown": shown,
                    "clicked": clicked,
                    "ctr": round((clicked / shown) if shown else 0.0, 4),
                    "completion_after_click_rate": round(
                        (completed / clicked) if clicked else 0.0,
                        4,
                    ),
                }
            )
        top_resources.sort(
            key=lambda item: (item.get("clicked", 0), item.get("shown", 0)),
            reverse=True,
        )

        shown_count = len(shown_events)
        clicked_count = len(clicked_events)
        return {
            "window_days": max(1, days),
            "shown_count": shown_count,
            "clicked_count": clicked_count,
            "ctr": round((clicked_count / shown_count) if shown_count else 0.0, 4),
            "completion_after_recommendation": {
                "completed_count": completion_after_click,
                "rate": round(
                    (completion_after_click / clicked_count) if clicked_count else 0.0,
                    4,
                ),
            },
            "confidence_gain_after_recommendation": {
                "avg_delta": round(
                    (sum(confidence_deltas) / len(confidence_deltas))
                    if confidence_deltas
                    else 0.0,
                    4,
                ),
                "sample_size": len(confidence_deltas),
            },
            "top_resources": top_resources[:5],
        }

    def research_learning_path_metrics(self, *, days: int = 30) -> Dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        paths = list(
            self.learning_paths.find(
                {},
                {
                    "path_id": 1,
                    "user_id": 1,
                    "lesson_progress": 1,
                    "chapters": 1,
                    "subject_id": 1,
                },
            )
        )

        total_paths = len(paths)
        completed_paths = 0
        completion_ratios: List[float] = []
        path_breakdown: List[Dict[str, Any]] = []
        lesson_title_map: Dict[str, str] = {}

        for path in paths:
            lesson_progress = path.get("lesson_progress") or {}
            if not isinstance(lesson_progress, dict):
                lesson_progress = {}

            total_lessons = len(lesson_progress)
            completed_lessons = sum(
                1
                for status in lesson_progress.values()
                if self._status(status) == "completed"
            )
            ratio = (completed_lessons / total_lessons) if total_lessons else 0.0
            completion_ratios.append(ratio)
            if total_lessons and completed_lessons == total_lessons:
                completed_paths += 1

            path_breakdown.append(
                {
                    "path_id": str(path.get("path_id") or ""),
                    "user_id": str(path.get("user_id") or ""),
                    "subject_id": str(path.get("subject_id") or ""),
                    "completion_rate": round(ratio, 4),
                    "completed_lessons": completed_lessons,
                    "total_lessons": total_lessons,
                }
            )

            for chapter in path.get("chapters") or []:
                for lesson in chapter.get("lessons") or []:
                    lesson_id = str(lesson.get("lesson_id") or "").strip()
                    if lesson_id and lesson_id not in lesson_title_map:
                        lesson_title_map[lesson_id] = str(
                            lesson.get("title") or chapter.get("title") or lesson_id
                        )

        lesson_events = self._combined_events(
            since=since,
            event_names=("lesson_opened", "lesson_completed"),
        )
        lesson_counters: Dict[str, Dict[str, int]] = {}
        for item in lesson_events:
            lesson_id = str(item.get("lesson_id") or "").strip()
            if not lesson_id:
                continue
            counter = lesson_counters.setdefault(
                lesson_id,
                {"opened": 0, "completed": 0},
            )
            if item.get("event_type") == "lesson_opened":
                counter["opened"] += 1
            elif item.get("event_type") == "lesson_completed":
                counter["completed"] += 1

        lesson_drop_off = []
        for lesson_id, counter in lesson_counters.items():
            opened = int(counter.get("opened") or 0)
            completed = int(counter.get("completed") or 0)
            if opened <= 0:
                continue
            lesson_drop_off.append(
                {
                    "lesson_id": lesson_id,
                    "lesson_title": lesson_title_map.get(lesson_id, lesson_id),
                    "opened": opened,
                    "completed": completed,
                    "drop_off_rate": round(max(opened - completed, 0) / opened, 4),
                }
            )
        lesson_drop_off.sort(
            key=lambda item: (item["drop_off_rate"], item["opened"]),
            reverse=True,
        )

        refinement_count = self.path_refinement_actions.count_documents(
            {"created_at": {"$gte": since.replace(tzinfo=None)}}
        )
        intervention_rows = list(
            self.intervention_logs.find(
                {"created_at": {"$gte": since.replace(tzinfo=None)}},
                {"intervention_type": 1},
            )
        )
        bridge_insertions = sum(
            1
            for row in intervention_rows
            if str(row.get("intervention_type") or "") == "prerequisite_bridge"
        )
        intervention_type_counts: Dict[str, int] = {}
        for row in intervention_rows:
            key = str(row.get("intervention_type") or "unknown")
            intervention_type_counts[key] = intervention_type_counts.get(key, 0) + 1

        path_breakdown.sort(key=lambda item: item.get("completion_rate", 0.0))
        average_completion_rate = (
            sum(completion_ratios) / len(completion_ratios) if completion_ratios else 0.0
        )

        return {
            "window_days": max(1, days),
            "path_count": total_paths,
            "completed_path_count": completed_paths,
            "completion_rate": round(
                (completed_paths / total_paths) if total_paths else 0.0,
                4,
            ),
            "average_path_completion": round(average_completion_rate, 4),
            "lesson_drop_off": lesson_drop_off[:5],
            "refinement_count": refinement_count,
            "bridge_insertions": bridge_insertions,
            "intervention_type_counts": intervention_type_counts,
            "lowest_completion_paths": path_breakdown[:5],
        }

    def research_ai_tutor_metrics(self, *, days: int = 30) -> Dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        ask_rows = list(
            self.ask_history.find(
                {"timestamp": {"$gte": since}},
                {"user_id": 1, "timestamp": 1, "confidence": 1, "concept_name": 1},
            ).sort([("user_id", 1), ("timestamp", 1)])
        )
        total_asks = len(ask_rows)
        avg_answer_confidence = (
            sum(self._safe_float(item.get("confidence"), 0.0) for item in ask_rows)
            / total_asks
            if total_asks
            else 0.0
        )

        follow_up_count = 0
        follow_up_users: set[str] = set()
        ask_rows_by_user: Dict[str, List[datetime]] = {}
        for row in ask_rows:
            user_id = str(row.get("user_id") or "").strip()
            timestamp = self._normalize_datetime(row.get("timestamp"))
            if not user_id or not isinstance(timestamp, datetime):
                continue
            ask_rows_by_user.setdefault(user_id, []).append(timestamp)

        for user_id, timestamps in ask_rows_by_user.items():
            timestamps.sort()
            for index in range(len(timestamps) - 1):
                if timestamps[index + 1] - timestamps[index] <= timedelta(minutes=10):
                    follow_up_count += 1
                    follow_up_users.add(user_id)

        ai_response_events = self._combined_events(
            since=since,
            event_names=("ai_response_generated",),
        )
        llm_events = self._combined_events(since=since, event_names=("llm_called",))
        retrieval_hits = 0
        latency_values: List[int] = []
        source_counts: List[int] = []

        for item in ai_response_events:
            metadata = self._event_metadata(item)
            source_count = int(metadata.get("sources") or 0)
            source_counts.append(source_count)
            if source_count > 0:
                retrieval_hits += 1

        for item in llm_events:
            latency = int(item.get("latency_ms") or item.get("duration_ms") or 0)
            if latency > 0:
                latency_values.append(latency)

        return {
            "window_days": max(1, days),
            "total_asks": total_asks,
            "retrieval_hit_ratio": round(
                (retrieval_hits / len(ai_response_events))
                if ai_response_events
                else 0.0,
                4,
            ),
            "average_answer_confidence": round(avg_answer_confidence, 4),
            "follow_up_ask_rate": round(
                (follow_up_count / total_asks) if total_asks else 0.0,
                4,
            ),
            "follow_up_users": len(follow_up_users),
            "average_retrieval_sources": round(
                (sum(source_counts) / len(source_counts)) if source_counts else 0.0,
                4,
            ),
            "average_latency_ms": round(
                (sum(latency_values) / len(latency_values))
                if latency_values
                else 0.0,
                2,
            ),
            "llm_call_count": len(llm_events),
        }

    def admin_research_dashboard(self, *, days: int = 30) -> Dict[str, Any]:
        return {
            "window_days": max(1, days),
            "recommendation": self.research_recommendation_metrics(days=days),
            "learning_path": self.research_learning_path_metrics(days=days),
            "ai_tutor": self.research_ai_tutor_metrics(days=days),
            "analytics_schema_version": "analytics.research.v1",
            "source_of_truth": analytics_metadata(),
        }
