"""
Exercise Logging Service: Handles quiz/exercise attempt logging and history retrieval.

Integrates with:
- learning_path_service: Captures confidence scores from quiz submissions
- exercise_attempt_repository: Persists attempt data
- lesson_service: Retrieves lesson information for logging

Logs are created when:
1. User submits quiz with confidence score
2. Exercise auto-completes or progress is recorded
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from backend.app.database.mongo import get_db
from backend.app.repositories.exercise_attempt_repository import (
    ExerciseAttemptRepository,
)

logger = logging.getLogger(__name__)


class ExerciseLoggingService:
    """Service for logging and retrieving exercise attempt history."""

    def __init__(self, db, exercise_attempt_repository):
        self.db = db
        self.repository = exercise_attempt_repository

    def log_quiz_attempt(
        self,
        user_id: str,
        path_id: str,
        lesson_id: str,
        questions_data: List[Dict[str, Any]],
        confidence: float,
        auto_completed: bool,
        lesson_status_after: str,
    ) -> Dict[str, Any]:
        """
        Log a quiz/exercise attempt with detailed answer tracking.

        Args:
            user_id: User ID
            path_id: Learning path ID
            lesson_id: Lesson ID
            questions_data: Array of question objects with user answers
                [
                    {
                        "question_id": "q1",
                        "question_text": "What is Python?",
                        "user_answer": "A programming language",
                        "correct_answer": "A programming language",
                        "is_correct": True,
                        "score": 1.0
                    },
                    ...
                ]
            confidence: Overall confidence score (0-1)
            auto_completed: Whether lesson auto-completed
            lesson_status_after: Lesson status after attempt

        Returns:
            Logged attempt document
        """
        try:
            normalized_questions = self._normalize_questions(questions_data)
            if not normalized_questions:
                raise ValueError(
                    "questions_data must contain at least one valid answered question"
                )

            bounded_confidence = min(1.0, max(0.0, float(confidence)))

            # Get current attempt number
            attempt_number = self._get_next_attempt_number(user_id, lesson_id)

            # Create attempt log
            attempt = self.repository.create_attempt(
                user_id=user_id,
                path_id=path_id,
                lesson_id=lesson_id,
                questions=normalized_questions,
                confidence=bounded_confidence,
                passed=auto_completed,
                status_after=lesson_status_after,
                attempt_number=attempt_number,
            )

            logger.info(
                f"Logged quiz attempt: user={user_id}, lesson={lesson_id}, "
                f"attempt={attempt_number}, questions={len(normalized_questions)}, "
                f"confidence={bounded_confidence:.2%}, auto_completed={auto_completed}"
            )

            return attempt

        except Exception as e:
            logger.error(f"Failed to log quiz attempt: {e}")
            raise

    def _normalize_questions(
        self, questions_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Normalize and validate question payload before persistence."""
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(questions_data or []):
            if not isinstance(raw, dict):
                continue

            question_id = (
                str(raw.get("question_id") or "").strip() or f"unknown_{index + 1}"
            )
            question_text = str(raw.get("question") or "").strip()
            question_type = (
                str(raw.get("question_type") or "multiple_choice").strip()
                or "multiple_choice"
            )
            user_answer = str(raw.get("user_answer") or "").strip()
            correct_answer = str(raw.get("correct_answer") or "").strip()

            raw_is_correct = raw.get("is_correct")
            if isinstance(raw_is_correct, bool):
                is_correct = raw_is_correct
            else:
                is_correct = (
                    bool(user_answer)
                    and user_answer.casefold() == correct_answer.casefold()
                )

            normalized.append(
                {
                    "question_id": question_id,
                    "question": question_text,
                    "question_type": question_type,
                    "user_answer": user_answer,
                    "correct_answer": correct_answer,
                    "is_correct": is_correct,
                    "difficulty": str(raw.get("difficulty") or "beginner"),
                    "bloom_level": str(raw.get("bloom_level") or "remember"),
                }
            )

        return normalized

    def _get_next_attempt_number(self, user_id: str, lesson_id: str) -> int:
        """
        Calculate the next attempt number for a lesson.
        """
        try:
            latest = self.repository.get_latest_attempt(user_id, lesson_id)
            if latest:
                return latest.get("attempt_number", 0) + 1
            return 1
        except Exception as e:
            logger.warning(f"Failed to get attempt number: {e}")
            return 1

    def get_lesson_history(
        self,
        user_id: str,
        lesson_id: str,
        include_stats: bool = True,
    ) -> Dict[str, Any]:
        """
        Get complete attempt history for a lesson with optional statistics.

        Returns:
            {
                "lesson_id": "lesson1",
                "attempts": [
                    {
                        "attempt_number": 1,
                        "confidence": 0.75,
                        "passed": True,
                        "correctly_answered": 3,
                        "total_questions": 4,
                        "created_at": "2025-03-25T10:30:00Z"
                    },
                    ...
                ],
                "statistics": {
                    "total_attempts": 3,
                    "passed_attempts": 2,
                    "best_confidence": 0.95,
                    "avg_confidence": 0.82,
                    "latest_confidence": 0.95,
                    "improvement": 0.20,
                    "success_rate": 0.667
                }
            }
        """
        try:
            attempts = self.repository.get_lesson_attempts(user_id, lesson_id)

            # Format attempts for API response
            formatted_attempts = []
            for attempt in attempts:
                questions = attempt.get("questions", [])
                correct_count = sum(1 for q in questions if q.get("is_correct"))

                formatted_attempts.append(
                    {
                        "attempt_number": attempt.get("attempt_number"),
                        "confidence": attempt.get("confidence"),
                        "confidence_percent": int(attempt.get("confidence", 0) * 100),
                        "passed": attempt.get("passed"),
                        "correctly_answered": correct_count,
                        "total_questions": len(questions),
                        "status_after": attempt.get("status_after"),
                        "created_at": (
                            attempt.get("created_at").isoformat()
                            if attempt.get("created_at")
                            else None
                        ),
                    }
                )

            result = {
                "lesson_id": lesson_id,
                "attempts": formatted_attempts,
            }

            if include_stats:
                result["statistics"] = self.repository.get_attempt_statistics(
                    user_id, lesson_id
                )

            logger.debug(f"Retrieved history for {user_id} on lesson {lesson_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to get lesson history: {e}")
            return {
                "lesson_id": lesson_id,
                "attempts": [],
                "statistics": {} if include_stats else None,
            }

    def get_path_history(
        self,
        user_id: str,
        path_id: str,
        group_by_lesson: bool = True,
    ) -> Dict[str, Any]:
        """
        Get attempt history for entire learning path.

        Args:
            user_id: User ID
            path_id: Learning path ID
            group_by_lesson: If True, group attempts by lesson

        Returns:
            Attempts grouped by lesson or flat list
        """
        try:
            attempts = self.repository.get_path_attempts(user_id, path_id)

            if not group_by_lesson:
                return {
                    "path_id": path_id,
                    "total_attempts": len(attempts),
                    "attempts": attempts,
                }

            # Group by lesson
            grouped = {}
            for attempt in attempts:
                lesson_id = attempt["lesson_id"]
                if lesson_id not in grouped:
                    grouped[lesson_id] = []
                grouped[lesson_id].append(attempt)

            result = {
                "path_id": path_id,
                "total_lessons": len(grouped),
                "total_attempts": len(attempts),
                "lessons": {
                    lesson_id: {
                        "lesson_id": lesson_id,
                        "attempt_count": len(attempts_list),
                        "latest_confidence": attempts_list[0].get("confidence"),
                        "best_confidence": max(
                            a.get("confidence", 0) for a in attempts_list
                        ),
                        "passed": any(a.get("passed") for a in attempts_list),
                    }
                    for lesson_id, attempts_list in grouped.items()
                },
            }

            logger.debug(f"Retrieved path history for {user_id} on path {path_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to get path history: {e}")
            return {"path_id": path_id, "lessons": {}}


db = get_db()
exercise_attempt_repository = ExerciseAttemptRepository(db)
exercise_logging_service = ExerciseLoggingService(db, exercise_attempt_repository)
