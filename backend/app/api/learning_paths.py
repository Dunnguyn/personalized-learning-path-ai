"""API routes for hybrid subject-scoped learning path generation."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    GeneratedLearningPathResponse,
    LearningPathDeleteResponse,
    LearningPathHistoryItemResponse,
    LearningPathGenerateRequest,
    LessonProgressResponse,
    LessonProgressUpdate,
)
from backend.app.services.learning_path_service import learning_path_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning-paths", tags=["Learning Paths"])


@router.post("/generate", response_model=GeneratedLearningPathResponse, status_code=status.HTTP_200_OK)
def generate_learning_path(payload: LearningPathGenerateRequest, current_user=Depends(get_current_user)):
    """Generate a subject-scoped learning path and freeze lesson chunk recommendations."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.generate_learning_path(
            subject_id=payload.subject_id.value,
            goal=payload.goal,
            level=payload.level.value,
            user_id=user_id,
        )
        return GeneratedLearningPathResponse(
            path_id=result["path_id"],
            subject_id=payload.subject_id,
            goal=result["goal"],
            level=payload.level,
            generated_at=result.get("generated_at"),
            chapters=result["chapters"],
            curriculum_source=result.get("curriculum_source", "fallback"),
            llm_status=result.get("llm_status"),
            message=result.get("message", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to generate hybrid learning path: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate learning path.",
        ) from exc


@router.get("/history", response_model=list[LearningPathHistoryItemResponse], status_code=status.HTTP_200_OK)
def get_learning_path_history(current_user=Depends(get_current_user)):
    """Return recent learning paths for the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        results = learning_path_service.list_learning_paths(user_id=user_id)
        history = []
        for item in results:
            history.append(
                LearningPathHistoryItemResponse(
                    path_id=item["path_id"],
                    subject_id=item["subject_id"],
                    goal=item["goal"],
                    level=item["level"],
                    generated_at=item["generated_at"],
                    chapter_count=len(item.get("chapters", [])),
                    lesson_count=sum(len(chapter.get("lessons", [])) for chapter in item.get("chapters", [])),
                )
            )
        return history
    except Exception as exc:
        logger.exception("Failed to load learning path history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learning path history.",
        ) from exc


@router.post("/lesson-progress", response_model=LessonProgressResponse, status_code=status.HTTP_200_OK)
def update_lesson_progress(payload: LessonProgressUpdate, current_user=Depends(get_current_user)):
    """Update lesson progress for a path owned by the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.update_lesson_progress(
            path_id=payload.path_id,
            user_id=user_id,
            lesson_id=payload.lesson_id,
            status=payload.status,
        )
        return LessonProgressResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update lesson progress: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update lesson progress.",
        ) from exc


@router.get("/{path_id}", response_model=GeneratedLearningPathResponse, status_code=status.HTTP_200_OK)
def get_learning_path(path_id: str, current_user=Depends(get_current_user)):
    """Return a previously generated subject-scoped learning path for the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.get_learning_path(path_id=path_id, user_id=user_id)
        return GeneratedLearningPathResponse(
            path_id=result["path_id"],
            subject_id=result["subject_id"],
            goal=result["goal"],
            level=result["level"],
            generated_at=result.get("generated_at"),
            chapters=result["chapters"],
            curriculum_source=result.get("curriculum_source", "fallback"),
            llm_status=result.get("llm_status"),
            message=result.get("message", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to load hybrid learning path: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learning path.",
        ) from exc


@router.delete("/{path_id}", response_model=LearningPathDeleteResponse, status_code=status.HTTP_200_OK)
def delete_learning_path(path_id: str, current_user=Depends(get_current_user)):
    """Delete a stored learning path and generated artifacts owned by the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.delete_learning_path(path_id=path_id, user_id=user_id)
        return LearningPathDeleteResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to delete learning path %s: %s", path_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete learning path.",
        ) from exc
