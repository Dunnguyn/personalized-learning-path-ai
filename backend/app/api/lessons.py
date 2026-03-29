"""API routes for lesson structure, recommended chunks, and question bank."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user, require_admin_user
from backend.app.api.schemas import (
    AdaptiveQuizNextRequest,
    AdaptiveQuizNextResponse,
    LessonCreate,
    LessonListResponse,
    LessonNodeResponse,
    LessonQuestionBankResponse,
    LessonQuestionGenerationRequest,
    LessonQuestionGenerationResponse,
    LessonRecommendedChunksRequest,
    LessonRecommendedChunksResponse,
)
from backend.app.services.adaptive_learning_service import adaptive_learning_service
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.question_generation_service import (
    lesson_question_generation_service,
)
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.feedback_service import feedback_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.adaptive_learning_loop_service import (
    adaptive_learning_loop_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["Lessons"])


@router.get("/", response_model=LessonListResponse, status_code=status.HTTP_200_OK)
def list_lessons(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = Query(None, description="Filter lessons by subject ID"),
    chapter_id: Optional[str] = Query(None, description="Filter lessons by chapter ID"),
    q: Optional[str] = Query(
        None, min_length=1, description="Search by title or summary"
    ),
    topic: Optional[str] = Query(None, min_length=1),
    level: Optional[str] = Query(None, min_length=1),
    current_user=Depends(get_current_user),
):
    """List lessons with pagination and optional filters."""
    del current_user
    try:
        return lesson_structure_service.list_lessons_paginated(
            page=page,
            size=size,
            subject_id=subject_id,
            chapter_id=chapter_id,
            q=q,
            topic=topic,
            level=level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to list lessons: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load lessons.",
        )


@router.post(
    "/", response_model=LessonNodeResponse, status_code=status.HTTP_201_CREATED
)
def create_lesson(payload: LessonCreate, current_user=Depends(require_admin_user)):
    """Create a lesson under a chapter."""
    del current_user
    try:
        return lesson_structure_service.create_lesson(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create lesson: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create lesson.",
        )


@router.get(
    "/{lesson_id}", response_model=LessonNodeResponse, status_code=status.HTTP_200_OK
)
def get_lesson(lesson_id: str, current_user=Depends(get_current_user)):
    """Get a single lesson."""
    user_id = str(current_user.get("_id", ""))
    try:
        lesson = lesson_structure_service.get_lesson(lesson_id)
        event_logging_service.log_event(
            "lesson_opened",
            user_id=user_id,
            lesson_id=lesson_id,
            chapter_id=lesson.get("chapter_id"),
            subject_id=lesson.get("subject_id"),
            success=True,
        )
        adaptive_learning_loop_service.ingest_learning_event(
            user_id=user_id,
            event_type="lesson_started",
            lesson_id=lesson_id,
            metadata={"source": "lessons_api"},
        )
        feedback_service.process_implicit_feedback(
            user_id=user_id,
            signal_type="lesson_opened",
            lesson_id=lesson_id,
            value=0.1,
            metadata={"source": "lesson_api"},
        )
        knowledge_tracing_service.update_from_interaction(
            user_id=user_id,
            event_type="lesson_opened",
            lesson_id=lesson_id,
            metadata={"source": "lesson_api"},
        )
        return lesson
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to get lesson %s: %s", lesson_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load lesson.",
        )


@router.post(
    "/{lesson_id}/recommended-chunks",
    response_model=LessonRecommendedChunksResponse,
    status_code=status.HTTP_200_OK,
)
def recommend_chunks_for_lesson(
    lesson_id: str,
    payload: LessonRecommendedChunksRequest,
    current_user=Depends(get_current_user),
):
    """Freeze recommended chunks for a lesson using local retrieval only."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = lesson_chunk_service.recommend_chunks(
            lesson_id=lesson_id,
            max_chunks=payload.max_chunks,
            selection_strategy=payload.selection_strategy,
            enable_diversity_reranking=payload.enable_diversity_reranking,
            diversity_lambda=payload.diversity_lambda,
            resource_ids=payload.resource_ids,
            metadata=payload.metadata,
        )
        recommendation_metadata = result.get("metadata", {}) or {}
        rerank_metadata = recommendation_metadata.get("diversity_reranking", {}) or {}
        rerank_strategy = str(rerank_metadata.get("strategy") or "")

        event_logging_service.log_event(
            "resource_recommended",
            user_id=user_id,
            lesson_id=lesson_id,
            success=True,
            metadata={"chunks": len(result.get("chunk_ids", []))},
        )
        if rerank_strategy == "rerank_failed_fallback":
            event_logging_service.log_event(
                "lesson_chunk_rerank_fallback",
                user_id=user_id,
                lesson_id=lesson_id,
                success=True,
                metadata={
                    "selection_strategy": payload.selection_strategy,
                    "max_chunks": payload.max_chunks,
                    "candidate_count": recommendation_metadata.get("candidate_count"),
                    "selected_count": recommendation_metadata.get("selected_count"),
                    "rerank_strategy": rerank_strategy,
                },
            )
        event_logging_service.log_event(
            "recommendation_shown",
            user_id=user_id,
            lesson_id=lesson_id,
            success=True,
            metadata={"selection_strategy": payload.selection_strategy},
        )
        feedback_service.process_implicit_feedback(
            user_id=user_id,
            signal_type="lesson_recommendation_shown",
            lesson_id=lesson_id,
            value=0.2,
            metadata={"selection_strategy": payload.selection_strategy},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to recommend lesson chunks: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not recommend chunks for lesson.",
        )


@router.get(
    "/{lesson_id}/recommended-chunks",
    response_model=LessonRecommendedChunksResponse,
    status_code=status.HTTP_200_OK,
)
def get_recommended_chunks_for_lesson(
    lesson_id: str, current_user=Depends(get_current_user)
):
    """Load previously frozen recommended chunks for a lesson."""
    user_id = str(current_user.get("_id", ""))
    try:
        result = lesson_chunk_service.get_recommendation(lesson_id)
        event_logging_service.log_event(
            "recommendation_shown",
            user_id=user_id,
            lesson_id=lesson_id,
            success=True,
            metadata={"chunks": len(result.get("chunk_ids", []))},
        )
        feedback_service.process_implicit_feedback(
            user_id=user_id,
            signal_type="lesson_recommendation_opened",
            lesson_id=lesson_id,
            value=0.15,
            metadata={"chunks": len(result.get("chunk_ids", []))},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to load lesson recommendation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load lesson recommended chunks.",
        )


@router.post(
    "/{lesson_id}/generate-questions",
    response_model=LessonQuestionGenerationResponse,
    status_code=status.HTTP_200_OK,
)
def generate_questions_for_lesson(
    lesson_id: str,
    payload: LessonQuestionGenerationRequest,
):
    """Generate lesson questions only from already recommended chunks."""
    try:
        return lesson_question_generation_service.generate_questions_for_lesson(
            lesson_id=lesson_id,
            target_count=payload.target_count,
            question_types=[item.value for item in payload.question_types],
            difficulty=payload.difficulty.value,
            bloom_levels=[item.value for item in payload.bloom_levels],
            allow_llm=payload.allow_llm,
            mastery=payload.mastery,
            success_rate=payload.success_rate,
            overwrite=payload.overwrite,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to generate lesson questions: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate lesson questions.",
        )


@router.get(
    "/{lesson_id}/questions",
    response_model=LessonQuestionBankResponse,
    status_code=status.HTTP_200_OK,
)
def get_question_bank_for_lesson(lesson_id: str):
    """Return the lesson-scoped question bank."""
    try:
        return lesson_question_generation_service.get_questions_for_lesson(lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to load lesson question bank: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load lesson question bank.",
        )


@router.post(
    "/{lesson_id}/adaptive-quiz/next",
    response_model=AdaptiveQuizNextResponse,
    status_code=status.HTTP_200_OK,
)
def get_next_adaptive_quiz(
    lesson_id: str,
    payload: AdaptiveQuizNextRequest,
    current_user=Depends(get_current_user),
):
    """Generate next adaptive quiz request and question set for a lesson."""
    user_id = str(current_user.get("_id", ""))
    try:
        config = adaptive_learning_service.build_next_quiz_request(
            user_id=user_id,
            lesson_id=lesson_id,
            target_count=payload.target_count,
        )
        generated = lesson_question_generation_service.generate_questions_for_lesson(
            lesson_id=lesson_id,
            target_count=int(config.get("target_count", payload.target_count)),
            question_types=["multiple_choice", "short_answer", "true_false"],
            difficulty=str(config.get("recommended_difficulty") or "beginner"),
            bloom_levels=list(
                config.get("recommended_bloom_levels")
                or ["remember", "understand"]
            ),
            allow_llm=bool(
                config.get("generation_strategy", {}).get("allow_llm", False)
            ),
            mastery=None,
            success_rate=None,
            overwrite=True,
            metadata={
                "adaptive_quiz": True,
                "path_id": payload.path_id,
                "target_chunk_ids": config.get("target_chunk_ids", []),
                "target_concepts": config.get("target_concepts", []),
                "retry_strategy": config.get("retry_strategy", "same_question"),
                "adaptive_explanation": config.get("explanation"),
                "prefer_template": bool(
                    config.get("generation_strategy", {}).get("prefer_template", True)
                ),
                "generation_strategy": config.get("generation_strategy", {}),
            },
        )
        return AdaptiveQuizNextResponse(
            lesson_id=lesson_id,
            next_action={
                "type": "adaptive_quiz_next",
                "recommended_difficulty": config.get("recommended_difficulty"),
                "recommended_bloom_levels": config.get(
                    "recommended_bloom_levels", []
                ),
                "target_chunk_ids": config.get("target_chunk_ids", []),
                "target_concepts": config.get("target_concepts", []),
            },
            generation_request=config,
            generated=generated,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to generate adaptive next quiz: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate adaptive next quiz.",
        )
