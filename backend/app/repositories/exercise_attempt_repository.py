"""
Exercise Attempt Repository: Track and retrieve quiz/exercise submission history for each lesson.

Features:
- Log every quiz/exercise attempt with answers and scores
- Retrieve attempt history per lesson/user
- Calculate attempt statistics (total attempts, best score, improvement)
- Export attempt data for analytics

Schema: exercise_attempts
- user_id: User identifier
- path_id: Learning path ID
- lesson_id: Lesson ID
- attempt_number: Attempt sequence (1, 2, 3...)
- questions: Array of question objects with answer details
- confidence: Final confidence score for this attempt
- passed: Whether attempt auto-completed (confidence >= 75%)
- status_after: Lesson status after attempt
- created_at: When attempt occurred
- updated_at: Last modification timestamp
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from bson import ObjectId

logger = logging.getLogger(__name__)


class ExerciseAttemptRepository:
    """Manages exercise attempt history logging and retrieval."""

    _BLOOM_WEIGHTS = {
        "remember": 0.25,
        "understand": 0.25,
        "apply": 0.30,
        "analyze": 0.20,
    }

    def __init__(self, db):
        self.db = db
        self.collection = db.exercise_attempts
        self._create_indexes()

    def _create_indexes(self):
        """Create indexes for efficient querying."""
        try:
            self.collection.create_index(
                [("user_id", 1), ("lesson_id", 1), ("created_at", -1)]
            )
            self.collection.create_index(
                [("user_id", 1), ("path_id", 1), ("created_at", -1)]
            )
            self.collection.create_index([("lesson_id", 1), ("passed", 1)])
            logger.info("Exercise attempt indexes created successfully")
        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")

    @staticmethod
    def _as_nullable_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @classmethod
    def _derive_bloom_score_from_accuracy_map(
        cls,
        bloom_accuracy_by_level: Dict[str, Any] | None,
    ) -> Optional[float]:
        if not isinstance(bloom_accuracy_by_level, dict) or not bloom_accuracy_by_level:
            return None

        weighted_score = 0.0
        has_any_value = False
        for level, weight in cls._BLOOM_WEIGHTS.items():
            try:
                value = bloom_accuracy_by_level.get(level)
                if value is None:
                    continue
                accuracy = float(value)
            except Exception:
                continue
            has_any_value = True
            weighted_score += float(weight) * max(0.0, min(1.0, accuracy))

        if not has_any_value:
            return None
        return round(max(0.0, min(1.0, weighted_score)), 4)

    @classmethod
    def _derive_bloom_score_from_questions(
        cls,
        questions: List[Dict[str, Any]] | None,
    ) -> Optional[float]:
        if not questions:
            return None

        grouped: Dict[str, List[bool]] = {}
        for question in questions:
            if not isinstance(question, dict):
                continue
            level = str(question.get("bloom_level") or "").strip().lower()
            if level not in cls._BLOOM_WEIGHTS:
                continue
            grouped.setdefault(level, []).append(bool(question.get("is_correct")))

        if not grouped:
            return None

        weighted_score = 0.0
        for level, weight in cls._BLOOM_WEIGHTS.items():
            answers = grouped.get(level) or []
            if not answers:
                continue
            accuracy = sum(1 for value in answers if value) / max(1, len(answers))
            weighted_score += float(weight) * float(accuracy)

        return round(max(0.0, min(1.0, weighted_score)), 4)

    @classmethod
    def _resolve_attempt_bloom_score(cls, attempt: Dict[str, Any]) -> Optional[float]:
        derived = cls._derive_bloom_score_from_questions(attempt.get("questions"))
        if derived is None:
            derived = cls._derive_bloom_score_from_accuracy_map(
                attempt.get("bloom_accuracy_by_level")
            )
        stored = cls._as_nullable_float(attempt.get("bloom_score"))
        if derived is not None:
            return derived
        return stored

    @staticmethod
    def _resolve_attempt_mastery_score(attempt: Dict[str, Any]) -> float:
        try:
            return float(attempt.get("mastery_score", 0.0) or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _resolve_attempt_confidence(attempt: Dict[str, Any]) -> float:
        try:
            return float(attempt.get("confidence", 0.0) or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _completion_rank(attempt: Dict[str, Any]) -> int:
        status = str(attempt.get("completion_status") or "").strip().lower()
        if status == "completed":
            return 3
        if status == "reinforce_required":
            return 2
        if status == "retry_required":
            return 1
        return 0

    @classmethod
    def _select_best_attempt(cls, attempts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not attempts:
            return None

        completed_attempts = [
            attempt
            for attempt in attempts
            if bool(attempt.get("passed"))
            or str(attempt.get("completion_status") or "").strip().lower() == "completed"
        ]
        candidate_attempts = completed_attempts or attempts

        def sort_key(attempt: Dict[str, Any]) -> tuple[float, float, float, int, int]:
            bloom_score = cls._resolve_attempt_bloom_score(attempt)
            try:
                attempt_number = int(attempt.get("attempt_number") or 0)
            except Exception:
                attempt_number = 0
            return (
                cls._resolve_attempt_mastery_score(attempt),
                float(bloom_score or 0.0),
                cls._resolve_attempt_confidence(attempt),
                cls._completion_rank(attempt),
                attempt_number,
            )

        return max(candidate_attempts, key=sort_key)

    def create_attempt(
        self,
        user_id: str,
        path_id: str,
        lesson_id: str,
        questions: List[Dict[str, Any]],
        confidence: float,
        passed: bool,
        status_after: str,
        attempt_number: int,
        attempt_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Log a new exercise/quiz attempt.

        Args:
            user_id: User ID
            path_id: Learning path ID
            lesson_id: Lesson ID
            questions: List of question objects with answers
                [
                    {
                        "question_id": "q1",
                        "question_text": "What is...",
                        "user_answer": "answer text",
                        "correct_answer": "correct answer",
                        "is_correct": True,
                        "score": 1.0
                    },
                    ...
                ]
            confidence: Overall confidence score (0-1)
            passed: Whether lesson auto-completed
            status_after: Lesson status after attempt ("completed", "in_progress", etc)
            attempt_number: Sequential attempt number

        Returns:
            Dict with attempt details and _id
        """
        try:
            now = datetime.utcnow()
            attempt = {
                "user_id": str(user_id),
                "path_id": str(path_id),
                "lesson_id": str(lesson_id),
                "attempt_number": attempt_number,
                "questions": questions,
                "confidence": float(confidence),
                "passed": bool(passed),
                "status_after": status_after,
                "created_at": now,
                "updated_at": now,
            }
            if isinstance(attempt_metrics, dict):
                attempt.update(
                    {
                        "mastery_score": attempt_metrics.get("mastery_score"),
                        "completion_status": attempt_metrics.get("completion_status"),
                        "reinforce_required": bool(
                            attempt_metrics.get("reinforce_required")
                        ),
                        "retry_required": bool(
                            attempt_metrics.get("retry_required")
                        ),
                        "bloom_score": attempt_metrics.get("bloom_score"),
                        "bloom_accuracy_by_level": dict(
                            attempt_metrics.get("bloom_accuracy_by_level") or {}
                        ),
                        "concept_coverage_rate": attempt_metrics.get(
                            "concept_coverage_score"
                        ),
                    }
                )

            result = self.collection.insert_one(attempt)
            attempt["_id"] = result.inserted_id

            logger.info(
                f"Logged exercise attempt: user={user_id}, lesson={lesson_id}, "
                f"attempt={attempt_number}, confidence={confidence:.2%}, passed={passed}"
            )

            return attempt

        except Exception as e:
            logger.error(f"Failed to create exercise attempt: {e}")
            raise

    def get_lesson_attempts(
        self,
        user_id: str,
        lesson_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get all attempts for a lesson by user (newest first).

        Args:
            user_id: User ID
            lesson_id: Lesson ID
            limit: Max attempts to return

        Returns:
            List of attempts, ordered by date descending
        """
        try:
            attempts = list(
                self.collection.find(
                    {
                        "user_id": str(user_id),
                        "lesson_id": str(lesson_id),
                    }
                )
                .sort("created_at", -1)
                .limit(limit)
            )

            logger.debug(
                f"Retrieved {len(attempts)} attempts: user={user_id}, lesson={lesson_id}"
            )

            return attempts

        except Exception as e:
            logger.error(f"Failed to get lesson attempts: {e}")
            return []

    def get_path_attempts(
        self,
        user_id: str,
        path_id: str,
        lesson_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Get all attempts in a learning path (optionally filtered by lesson).

        Args:
            user_id: User ID
            path_id: Learning path ID
            lesson_id: Optional, filter by specific lesson
            limit: Max attempts to return

        Returns:
            List of attempts, ordered by date descending
        """
        try:
            query = {
                "user_id": str(user_id),
                "path_id": str(path_id),
            }
            if lesson_id:
                query["lesson_id"] = str(lesson_id)

            attempts = list(
                self.collection.find(query).sort("created_at", -1).limit(limit)
            )

            logger.debug(
                f"Retrieved {len(attempts)} path attempts: user={user_id}, path={path_id}"
            )

            return attempts

        except Exception as e:
            logger.error(f"Failed to get path attempts: {e}")
            return []

    def get_attempt_statistics(
        self,
        user_id: str,
        lesson_id: str,
    ) -> Dict[str, Any]:
        """
        Calculate statistics for lesson attempts.

        Args:
            user_id: User ID
            lesson_id: Lesson ID

        Returns:
            Dict with statistics:
            - total_attempts: Number of attempts
            - passed_attempts: Number of successful attempts
            - best_confidence: Highest confidence score
            - avg_confidence: Average confidence
            - latest_confidence: Most recent confidence
            - improvement: Score difference from first to latest attempt
            - success_rate: Percentage of passed attempts
        """
        try:
            attempts = self.get_lesson_attempts(user_id, lesson_id, limit=1000)

            if not attempts:
                return {
                    "total_attempts": 0,
                    "passed_attempts": 0,
                    "best_confidence": None,
                    "best_bloom_score": None,
                    "avg_confidence": None,
                    "latest_confidence": None,
                    "improvement": None,
                    "success_rate": 0.0,
                    "best_mastery_score": None,
                    "latest_mastery_score": None,
                    "latest_completion_status": None,
                }

            confidences = [a["confidence"] for a in attempts]
            passed_count = sum(1 for a in attempts if a.get("passed"))
            bloom_scores = [
                score
                for score in (
                    self._resolve_attempt_bloom_score(attempt) for attempt in attempts
                )
                if score is not None
            ]

            stats = {
                "total_attempts": len(attempts),
                "passed_attempts": passed_count,
                "best_confidence": max(confidences),
                "best_bloom_score": max(bloom_scores) if bloom_scores else None,
                "avg_confidence": sum(confidences) / len(confidences),
                "latest_confidence": confidences[0],  # Most recent first
                "improvement": attempts[0]["confidence"] - attempts[-1]["confidence"],
                "success_rate": (passed_count / len(attempts)) if attempts else 0.0,
                "best_mastery_score": max(
                    float(a.get("mastery_score", 0.0) or 0.0) for a in attempts
                )
                if attempts
                else None,
                "latest_mastery_score": attempts[0].get("mastery_score"),
                "latest_completion_status": attempts[0].get("completion_status"),
            }

            best_attempt = self._select_best_attempt(attempts)
            if best_attempt:
                stats.update(
                    {
                        "best_attempt_confidence": self._resolve_attempt_confidence(
                            best_attempt
                        ),
                        "best_attempt_bloom_score": self._resolve_attempt_bloom_score(
                            best_attempt
                        ),
                        "best_attempt_mastery_score": self._resolve_attempt_mastery_score(
                            best_attempt
                        ),
                        "best_attempt_completion_status": best_attempt.get(
                            "completion_status"
                        ),
                        "best_attempt_number": best_attempt.get("attempt_number"),
                    }
                )

            logger.debug(
                f"Calculated statistics for {user_id} on lesson {lesson_id}: {stats}"
            )

            return stats

        except Exception as e:
            logger.error(f"Failed to get attempt statistics: {e}")
            return {}

    def get_latest_attempt(
        self,
        user_id: str,
        lesson_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent attempt for a lesson."""
        try:
            attempt = self.collection.find_one(
                {
                    "user_id": str(user_id),
                    "lesson_id": str(lesson_id),
                },
                sort=[("created_at", -1)],
            )
            return attempt
        except Exception as e:
            logger.error(f"Failed to get latest attempt: {e}")
            return None

    def delete_lesson_attempts(
        self,
        user_id: str,
        lesson_id: str,
    ) -> int:
        """Delete all attempts for a lesson (for cleanup/reset)."""
        try:
            result = self.collection.delete_many(
                {
                    "user_id": str(user_id),
                    "lesson_id": str(lesson_id),
                }
            )
            logger.info(
                f"Deleted {result.deleted_count} attempts: user={user_id}, lesson={lesson_id}"
            )
            return result.deleted_count
        except Exception as e:
            logger.error(f"Failed to delete lesson attempts: {e}")
            return 0
