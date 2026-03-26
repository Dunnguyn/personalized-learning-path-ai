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
    LessonStudyTimeResponse,
    LessonStudyTimeUpdate,
    StudySummaryResponse,
)
from backend.app.services.learning_path_service import learning_path_service
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.feedback_service import feedback_service
from backend.app.services.path_refinement_service import path_refinement_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning-paths", tags=["Learning Paths"])


@router.post(
    "/generate",
    response_model=GeneratedLearningPathResponse,
    status_code=status.HTTP_200_OK,
)
def generate_learning_path(
    payload: LearningPathGenerateRequest, current_user=Depends(get_current_user)
):
    """Generate a subject-scoped learning path and freeze lesson chunk recommendations."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.generate_learning_path(
            subject_id=payload.subject_id.value,
            goal=payload.goal,
            level=payload.level.value,
            user_id=user_id,
        )
        initialized_states = knowledge_tracing_service.bootstrap_from_generated_path(
            user_id=user_id,
            path_id=result.get("path_id", ""),
            subject_id=payload.subject_id.value,
            chapters=result.get("chapters", []),
        )
        event_logging_service.log_event(
            "learning_path_generated",
            user_id=user_id,
            subject_id=payload.subject_id.value,
            path_id=result.get("path_id"),
            success=True,
            metadata={
                "level": payload.level.value,
                "goal": payload.goal[:200],
                "kt_states_initialized": initialized_states,
            },
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
        event_logging_service.log_event(
            "learning_path_generated",
            user_id=user_id,
            subject_id=payload.subject_id.value,
            success=False,
            error_code="VALUE_ERROR",
            metadata={"detail": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to generate hybrid learning path: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate learning path.",
        ) from exc


@router.get(
    "/history",
    response_model=list[LearningPathHistoryItemResponse],
    status_code=status.HTTP_200_OK,
)
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
                    lesson_count=sum(
                        len(chapter.get("lessons", []))
                        for chapter in item.get("chapters", [])
                    ),
                )
            )
        return history
    except Exception as exc:
        logger.exception("Failed to load learning path history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learning path history.",
        ) from exc


@router.post(
    "/lesson-progress",
    response_model=LessonProgressResponse,
    status_code=status.HTTP_200_OK,
)
def update_lesson_progress(
    payload: LessonProgressUpdate, current_user=Depends(get_current_user)
):
    """
    Update lesson progress for a path owned by the current user.

    Rules:
    - Confidence must be >= 75% to complete a lesson (auto-complete if confidence >= 75%)
    - If confidence < 75%, completion is blocked; stay at in_progress
    - Locked lessons cannot be completed (previous lesson must be completed first)
    - To access next lesson, must complete current lesson (confidence >= 75%)
    """
    user_id = str(current_user.get("_id", ""))
    try:
        questions_answered = (
            [item.model_dump() for item in payload.questions_answered]
            if payload.questions_answered
            else None
        )
        result = learning_path_service.update_lesson_progress(
            path_id=payload.path_id,
            user_id=user_id,
            lesson_id=payload.lesson_id,
            status=payload.status,
            confidence=payload.confidence,
            questions_answered=questions_answered,
        )
        if payload.status == "completed" or result.get("status") == "completed":
            event_logging_service.log_event(
                "lesson_completed",
                user_id=user_id,
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                success=result.get("status") == "completed",
                confidence_after=result.get("last_confidence"),
            )
        if payload.confidence is not None and payload.questions_answered:
            event_logging_service.log_event(
                "confidence_updated",
                user_id=user_id,
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                confidence_after=payload.confidence,
                success=True,
            )
        if payload.questions_answered:
            event_logging_service.log_event(
                "quiz_submitted",
                user_id=user_id,
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                metadata={"questions": len(payload.questions_answered)},
                success=True,
            )

            correct_count = sum(
                1 for item in (questions_answered or []) if bool(item.get("is_correct"))
            )
            total_count = len(questions_answered or [])
            accuracy = (correct_count / total_count) if total_count > 0 else 0.0
            repeated_attempt = total_count > 0 and accuracy < 0.5

            knowledge_tracing_service.update_from_interaction(
                user_id=user_id,
                event_type="quiz_submitted",
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                confidence=payload.confidence,
                is_correct=(accuracy >= 0.6),
                repeated_attempt=repeated_attempt,
                metadata={
                    "source": "lesson_progress_api",
                    "accuracy": round(accuracy, 4),
                },
            )

            feedback_service.process_outcome_feedback(
                user_id=user_id,
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                quiz_accuracy=accuracy,
                completion_rate=1.0 if result.get("status") == "completed" else 0.0,
                confidence_gain=float(payload.confidence or 0.0),
                metadata={"questions": total_count},
            )

            feedback_service.process_implicit_feedback(
                user_id=user_id,
                signal_type=(
                    "repeated_attempt" if repeated_attempt else "stable_attempt"
                ),
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                value=-0.6 if repeated_attempt else 0.2,
                metadata={"accuracy": round(accuracy, 4)},
            )

            if repeated_attempt or (
                payload.confidence is not None and float(payload.confidence) < 0.5
            ):
                path_refinement_service.refine_path(
                    path_id=payload.path_id,
                    user_id=user_id,
                    lesson_id=payload.lesson_id,
                    trigger_reason="low_quiz_performance",
                    dry_run=False,
                )

        if result.get("status") == "completed":
            knowledge_tracing_service.update_from_interaction(
                user_id=user_id,
                event_type="lesson_completed",
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                confidence=result.get("last_confidence"),
                is_correct=True,
                metadata={"source": "lesson_progress_api"},
            )

        return LessonProgressResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to update lesson progress: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update lesson progress.",
        ) from exc


@router.get("/{path_id}/lesson-locks", status_code=status.HTTP_200_OK)
def get_lesson_lock_statuses(path_id: str, current_user=Depends(get_current_user)):
    """
    Get lock status for all lessons in a learning path.

    Returns dict mapping lesson_id -> {is_locked: bool, reason: str, blocking_lesson_id: str|null}
    """
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.get_lesson_lock_statuses(
            path_id=path_id,
            user_id=user_id,
        )
        return {
            "success": True,
            "path_id": path_id,
            "lesson_locks": result,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to get lesson lock statuses: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not get lesson lock statuses.",
        ) from exc


@router.post(
    "/study-time",
    response_model=LessonStudyTimeResponse,
    status_code=status.HTTP_200_OK,
)
def record_lesson_study_time(
    payload: LessonStudyTimeUpdate, current_user=Depends(get_current_user)
):
    """Record accumulated lesson study time for the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.record_lesson_study_time(
            path_id=payload.path_id,
            user_id=user_id,
            lesson_id=payload.lesson_id,
            seconds_spent=payload.seconds_spent,
        )
        knowledge_tracing_service.update_from_interaction(
            user_id=user_id,
            event_type="time_spent",
            path_id=payload.path_id,
            lesson_id=payload.lesson_id,
            time_spent_seconds=float(payload.seconds_spent),
            metadata={"source": "study_time_api"},
        )
        feedback_service.process_implicit_feedback(
            user_id=user_id,
            signal_type="time_spent",
            path_id=payload.path_id,
            lesson_id=payload.lesson_id,
            value=min(1.0, float(payload.seconds_spent) / 1800.0),
            metadata={"seconds_spent": payload.seconds_spent},
        )
        return LessonStudyTimeResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to record lesson study time: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record lesson study time.",
        ) from exc


@router.get(
    "/study-summary",
    response_model=StudySummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_study_summary(current_user=Depends(get_current_user)):
    """Return aggregated study time and recent calendar data for the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.get_study_summary(user_id=user_id, days=7)
        return StudySummaryResponse(**result)
    except Exception as exc:
        logger.exception("Failed to load study summary: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load study summary.",
        ) from exc


@router.get(
    "/{path_id}",
    response_model=GeneratedLearningPathResponse,
    status_code=status.HTTP_200_OK,
)
def get_learning_path(path_id: str, current_user=Depends(get_current_user)):
    """Return a previously generated subject-scoped learning path for the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.get_learning_path(
            path_id=path_id, user_id=user_id
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to load hybrid learning path: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learning path.",
        ) from exc


@router.delete(
    "/{path_id}",
    response_model=LearningPathDeleteResponse,
    status_code=status.HTTP_200_OK,
)
def delete_learning_path(path_id: str, current_user=Depends(get_current_user)):
    """Delete a stored learning path and generated artifacts owned by the current user."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = learning_path_service.delete_learning_path(
            path_id=path_id, user_id=user_id
        )
        return LearningPathDeleteResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to delete learning path %s: %s", path_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete learning path.",
        ) from exc
