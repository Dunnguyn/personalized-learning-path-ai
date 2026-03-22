"""
Learning Path API: Generate personalized learning paths for users.

Endpoints:
- POST /learning-path/generate: Generate adaptive learning path for user
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    LearningPathResponse,
    LessonProgressResponse,
    LessonProgressUpdate,
    LevelEnum,
)
from backend.app.services.learning_path.service import generate_learning_path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


def _build_lesson_progress(curriculum: Optional[List[dict]]) -> dict:
    progress = {}
    for chapter in curriculum or []:
        for lesson in chapter.get("lessons", []):
            lesson_id = lesson.get("lesson_id")
            if lesson_id and lesson_id not in progress:
                progress[lesson_id] = "not_started"
    return progress


def _apply_lesson_progress(curriculum: Optional[List[dict]], lesson_progress: dict) -> Optional[List[dict]]:
    if not curriculum:
        return curriculum

    for chapter in curriculum:
        for lesson in chapter.get("lessons", []):
            lesson_id = lesson.get("lesson_id")
            resolved_status = lesson_progress.get(lesson_id, "not_started") if lesson_id else "not_started"
            if lesson_id:
                lesson["status"] = resolved_status
    return curriculum


class LearningPathRequest(BaseModel):
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    goal: str = Field(..., min_length=3, max_length=500, description="Learning goal")
    level: LevelEnum = Field(..., description="Learning level (beginner/intermediate/advanced)")


@router.post("/generate", response_model=LearningPathResponse, status_code=status.HTTP_200_OK)
def generate_learning_path_api(
    payload: LearningPathRequest,
    current_user: dict = Depends(get_current_user)
):
    logger.info(
        "Learning path generation requested: user=%s, goal='%s...', level=%s",
        payload.user_id,
        payload.goal[:50],
        payload.level,
    )

    try:
        current_user_id = str(current_user.get("_id", ""))
        if current_user_id != payload.user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cannot generate learning path for another user",
            )

        result = generate_learning_path(
            user_id=payload.user_id,
            goal=payload.goal,
            level=payload.level.value if hasattr(payload.level, "value") else payload.level,
        )

        curriculum = _apply_lesson_progress(
            result.get("curriculum"),
            _build_lesson_progress(result.get("curriculum")),
        )

        try:
            from backend.app.database.mongo import get_db

            db = get_db()
            lesson_progress = _build_lesson_progress(curriculum)
            db.learning_paths.insert_one(
                {
                    "path_id": result.get("path_id"),
                    "user_id": payload.user_id,
                    "goal": payload.goal,
                    "level": payload.level.value if hasattr(payload.level, "value") else payload.level,
                    "generated_at": datetime.now(timezone.utc),
                    "recommended_path": result.get("recommended_path", []),
                    "curriculum": curriculum or [],
                    "curriculum_source": result.get("curriculum_source", "fallback"),
                    "curriculum_notice": result.get("curriculum_notice"),
                    "llm_status": result.get("llm_status"),
                    "lesson_progress": lesson_progress,
                    "message": result.get("message", "Learning path generated successfully"),
                }
            )
        except Exception as save_error:
            logger.warning("Failed to save learning path history: %s", save_error)

        return LearningPathResponse(
            path_id=result.get("path_id"),
            user_id=payload.user_id,
            goal=payload.goal,
            level=payload.level,
            generated_at=datetime.now(timezone.utc),
            recommended_path=result.get("recommended_path", []),
            curriculum=curriculum,
            curriculum_source=result.get("curriculum_source", "fallback"),
            curriculum_notice=result.get("curriculum_notice"),
            llm_status=result.get("llm_status"),
            message=result.get("message", "Learning path generated successfully"),
        )

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error generating learning path: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate learning path",
        ) from exc


@router.get("/history", status_code=status.HTTP_200_OK)
def get_learning_path_history(
    user_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    if user_id is None:
        user_id = str(current_user.get("_id", ""))

    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's path history",
        )

    try:
        from backend.app.database.mongo import get_db

        db = get_db()
        paths = list(db.learning_paths.find({"user_id": user_id}).sort("generated_at", -1).limit(10))

        for path in paths:
            if "_id" in path:
                path["_id"] = str(path["_id"])

        return {
            "success": True,
            "user_id": user_id,
            "paths": paths,
        }

    except Exception as exc:
        logger.exception("Error fetching path history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch learning path history",
        ) from exc


@router.post("/lesson-progress", response_model=LessonProgressResponse, status_code=status.HTTP_200_OK)
def update_lesson_progress(
    payload: LessonProgressUpdate,
    current_user: dict = Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))

    try:
        from backend.app.database.mongo import get_db

        db = get_db()
        path = db.learning_paths.find_one({"path_id": payload.path_id, "user_id": user_id})
        if not path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning path not found",
            )

        lesson_progress = path.get("lesson_progress", {})
        if payload.lesson_id not in lesson_progress:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lesson not found in learning path",
            )

        updated_at = datetime.now(timezone.utc)
        lesson_progress[payload.lesson_id] = payload.status

        db.learning_paths.update_one(
            {"_id": path.get("_id")},
            {"$set": {"lesson_progress": lesson_progress, "updated_at": updated_at}},
        )

        return LessonProgressResponse(
            path_id=payload.path_id,
            lesson_id=payload.lesson_id,
            status=payload.status,
            updated_at=updated_at,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating lesson progress: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update lesson progress",
        ) from exc


@router.get("/{path_id}", status_code=status.HTTP_200_OK)
def get_learning_path_detail(
    path_id: str,
    current_user: dict = Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))

    try:
        from backend.app.database.mongo import get_db

        db = get_db()
        path = db.learning_paths.find_one({"path_id": path_id, "user_id": user_id})

        if not path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning path not found",
            )

        lesson_progress = path.get("lesson_progress", {})
        path["curriculum"] = _apply_lesson_progress(path.get("curriculum"), lesson_progress)

        if "_id" in path:
            path["_id"] = str(path["_id"])

        return {
            "success": True,
            "path": path,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error fetching learning path detail: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch learning path detail",
        ) from exc
