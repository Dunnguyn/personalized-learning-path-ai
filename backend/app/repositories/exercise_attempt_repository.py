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
                    "avg_confidence": None,
                    "latest_confidence": None,
                    "improvement": None,
                    "success_rate": 0.0,
                }

            confidences = [a["confidence"] for a in attempts]
            passed_count = sum(1 for a in attempts if a.get("passed"))

            stats = {
                "total_attempts": len(attempts),
                "passed_attempts": passed_count,
                "best_confidence": max(confidences),
                "avg_confidence": sum(confidences) / len(confidences),
                "latest_confidence": confidences[0],  # Most recent first
                "improvement": attempts[0]["confidence"] - attempts[-1]["confidence"],
                "success_rate": (passed_count / len(attempts)) if attempts else 0.0,
            }

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
