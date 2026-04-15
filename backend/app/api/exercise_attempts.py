"""
Exercise Attempt History API: Endpoints for retrieving quiz/exercise attempt logs.

Provides:
- GET attempt history per lesson
- GET attempt history per learning path
- GET attempt statistics
- GET specific attempt details
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, status

from backend.app.api.schemas import LessonAttemptStatisticsResponse
from backend.app.services.exercise_logging_service import ExerciseLoggingService
from backend.app.repositories.exercise_attempt_repository import (
    ExerciseAttemptRepository,
)
from backend.app.database.mongo import get_db
from backend.app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/exercise_attempts", tags=["Exercise Attempts"])

# Initialize service and repository
db = get_db()
exercise_attempt_repo = ExerciseAttemptRepository(db)
exercise_logging_service = ExerciseLoggingService(db, exercise_attempt_repo)


@router.get("/lessons/{lesson_id}/attempts", status_code=status.HTTP_200_OK)
def get_lesson_attempts(
    lesson_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get attempt history for a specific lesson.

    Returns:
        {
            "lesson_id": "lesson1",
            "attempts": [
                {
                    "attempt_number": 1,
                    "confidence": 0.75,
                    "confidence_percent": 75,
                    "passed": true,
                    "correctly_answered": 3,
                    "total_questions": 4,
                    "status_after": "in_progress",
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
    user_id = str(current_user.get("_id", ""))
    try:
        history = exercise_logging_service.get_lesson_history(
            user_id=user_id,
            lesson_id=lesson_id,
            include_stats=True,
        )
        return history
    except Exception as exc:
        logger.exception(f"Failed to get lesson attempts: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve attempt history",
        ) from exc


@router.get("/learning-paths/{path_id}/attempts", status_code=status.HTTP_200_OK)
def get_path_attempts(
    path_id: str,
    lesson_id: str = None,
    current_user=Depends(get_current_user),
):
    """
    Get attempt history for a learning path (optionally filtered by lesson).

    Query Parameters:
        lesson_id (optional): Filter attempts for specific lesson

    Returns:
        {
            "path_id": "path1",
            "total_lessons": 5,
            "total_attempts": 12,
            "lessons": {
                "lesson1": {
                    "lesson_id": "lesson1",
                    "attempt_count": 3,
                    "latest_confidence": 0.95,
                    "best_confidence": 0.95,
                    "passed": true
                },
                ...
            }
        }
    """
    user_id = str(current_user.get("_id", ""))
    try:
        history = exercise_logging_service.get_path_history(
            user_id=user_id,
            path_id=path_id,
            group_by_lesson=True,
        )
        return history
    except Exception as exc:
        logger.exception(f"Failed to get path attempts: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve path attempt history",
        ) from exc


@router.get(
    "/lessons/{lesson_id}/statistics",
    response_model=LessonAttemptStatisticsResponse,
    status_code=status.HTTP_200_OK,
)
def get_lesson_statistics(
    lesson_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get performance statistics for a lesson.

    Returns:
        {
            "total_attempts": 3,
            "passed_attempts": 2,
            "best_confidence": 0.95,
            "avg_confidence": 0.82,
            "latest_confidence": 0.95,
            "improvement": 0.20,
            "success_rate": 0.667
        }
    """
    user_id = str(current_user.get("_id", ""))
    try:
        stats = exercise_attempt_repo.get_attempt_statistics(
            user_id=user_id,
            lesson_id=lesson_id,
        )
        return LessonAttemptStatisticsResponse(lesson_id=lesson_id, **(stats or {}))
    except Exception as exc:
        logger.exception(f"Failed to get lesson statistics: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve lesson statistics",
        ) from exc
