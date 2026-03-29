"""Repository methods for analytics aggregation from logs and progress data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


class AnalyticsRepository:
    """Aggregate learner/admin/system analytics from MongoDB collections."""

    def __init__(self, db):
        self.db = db
        self.event_logs = db.event_logs
        self.progress = db.progress
        self.learning_paths = db.learning_paths
        self.exercise_attempts = db.exercise_attempts
        self.users = db.users
        self.lesson_study_time = db["lesson_study_time"]

    @staticmethod
    def _to_date_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _max_timestamp(*timestamps: datetime | None) -> datetime | None:
        valid_timestamps = [item for item in timestamps if isinstance(item, datetime)]
        return max(valid_timestamps) if valid_timestamps else None

    def learner_completion_stats(self, user_id: str) -> Dict[str, Any]:
        paths = list(self.learning_paths.find({"user_id": user_id}))
        total_lessons = 0
        completed_lessons = 0
        in_progress_lessons = 0
        for path in paths:
            lesson_progress = path.get("lesson_progress", {}) or {}
            total_lessons += len(lesson_progress)
            completed_lessons += sum(
                1 for status in lesson_progress.values() if status == "completed"
            )
            in_progress_lessons += sum(
                1 for status in lesson_progress.values() if status == "in_progress"
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
        for history in by_concept.values():
            first = history[0]
            last = history[-1]
            mastery_gain += float(last.get("mastery", 0.0) or 0.0) - float(
                first.get("mastery", 0.0) or 0.0
            )
            confidence_gain += float(last.get("confidence", 0.0) or 0.0) - float(
                first.get("confidence", 0.0) or 0.0
            )

        overall_mastery = sum(float(r.get("mastery", 0.0) or 0.0) for r in rows) / len(
            rows
        )
        overall_confidence = sum(
            float(r.get("confidence", 0.0) or 0.0) for r in rows
        ) / len(rows)

        return {
            "mastery_gain": round(mastery_gain, 4),
            "confidence_gain": round(confidence_gain, 4),
            "overall_mastery": round(overall_mastery, 4),
            "overall_confidence": round(overall_confidence, 4),
        }

    def learner_time_and_streak(self, user_id: str) -> Dict[str, Any]:
        paths = list(self.learning_paths.find({"user_id": user_id}))
        time_per_lesson: Dict[str, int] = {}
        for path in paths:
            for lesson_id, seconds in (path.get("lesson_study_time") or {}).items():
                time_per_lesson[str(lesson_id)] = time_per_lesson.get(
                    str(lesson_id), 0
                ) + int(seconds or 0)

        now = datetime.now(timezone.utc)
        recent_events = list(
            self.event_logs.find(
                {
                    "user_id": user_id,
                    "timestamp": {"$gte": now - timedelta(days=30)},
                    "event_type": {
                        "$in": [
                            "lesson_opened",
                            "quiz_submitted",
                            "lesson_completed",
                            "resource_clicked",
                        ]
                    },
                },
                {"timestamp": 1},
            ).sort("timestamp", -1)
        )

        active_days = sorted(
            {
                self._to_date_key(item["timestamp"])
                for item in recent_events
                if item.get("timestamp")
            }
        )
        streak = 0
        cursor_day = now.date()
        active_set = set(active_days)
        while cursor_day.strftime("%Y-%m-%d") in active_set:
            streak += 1
            cursor_day = cursor_day - timedelta(days=1)

        session_events = list(
            self.event_logs.find({"user_id": user_id, "session_id": {"$ne": None}})
        )
        session_ranges: Dict[str, List[datetime]] = {}
        for event in session_events:
            session_id = str(event.get("session_id"))
            ts = event.get("timestamp")
            if not ts:
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
        shown = self.event_logs.count_documents(
            {"user_id": user_id, "event_type": "recommendation_shown"}
        )
        clicked = self.event_logs.count_documents(
            {"user_id": user_id, "event_type": "recommendation_clicked"}
        )
        resource_click = self.event_logs.count_documents(
            {"user_id": user_id, "event_type": "resource_clicked"}
        )
        resource_done = self.event_logs.count_documents(
            {"user_id": user_id, "event_type": "resource_completed"}
        )

        attempts = list(self.exercise_attempts.find({"user_id": user_id}))
        total_questions = 0
        total_correct = 0
        retry_attempts = 0
        by_lesson: Dict[str, int] = {}
        for attempt in attempts:
            lesson_id = str(attempt.get("lesson_id"))
            by_lesson[lesson_id] = by_lesson.get(lesson_id, 0) + 1
            questions = attempt.get("questions", []) or []
            total_questions += len(questions)
            total_correct += sum(1 for q in questions if bool(q.get("is_correct")))

        retry_attempts = sum(max(count - 1, 0) for count in by_lesson.values())
        retry_rate = (retry_attempts / len(attempts)) if attempts else 0.0
        quiz_accuracy = (total_correct / total_questions) if total_questions else 0.0
        recommendation_ctr = (clicked / shown) if shown else 0.0
        resource_completion_after_click = (
            (resource_done / resource_click) if resource_click else 0.0
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

    def admin_overview(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        dau = len(
            self.event_logs.distinct(
                "user_id", {"timestamp": {"$gte": day_ago}, "user_id": {"$ne": None}}
            )
        )
        wau = len(
            self.event_logs.distinct(
                "user_id", {"timestamp": {"$gte": week_ago}, "user_id": {"$ne": None}}
            )
        )

        lp_total = self.event_logs.count_documents(
            {"event_type": "learning_path_generated"}
        )
        lp_success = self.event_logs.count_documents(
            {"event_type": "learning_path_generated", "success": True}
        )

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
                {"event_type": {"$in": ["api_called", "api_failed"]}},
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
            1 for item in api_events if item.get("event_type") == "api_failed"
        )

        def percentile(values: List[int], p: float) -> float:
            if not values:
                return 0.0
            idx = int((len(values) - 1) * p)
            return float(values[idx])

        llm_calls = list(
            self.event_logs.find({"event_type": "llm_called"}, {"cost_estimate": 1})
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
        lp_total = self.event_logs.count_documents(
            {"event_type": "learning_path_generated"}
        )
        user_event_count = self.event_logs.count_documents({"user_id": {"$ne": None}})
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
        latest_study_time = self.lesson_study_time.find_one(
            {}, {"updated_at": 1}, sort=[("updated_at", -1)]
        )
        latest_user = self.users.find_one(
            {},
            {"updated_at": 1, "created_at": 1},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        updated_at = self._max_timestamp(
            latest_event.get("timestamp") if latest_event else None,
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
        }
