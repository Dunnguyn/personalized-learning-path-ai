"""API routes for lesson structure, recommended chunks, and question bank."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    LessonCreate,
    LessonListResponse,
    LessonNodeResponse,
    LessonQuestionBankResponse,
    LessonQuestionGenerationRequest,
    LessonQuestionGenerationResponse,
    LessonRecommendedChunksRequest,
    LessonRecommendedChunksResponse,
)
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.question_generation_service import lesson_question_generation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["Lessons"])


@router.get("/", response_model=LessonListResponse, status_code=status.HTTP_200_OK)
def list_lessons(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = Query(None, description="Filter lessons by subject ID"),
    chapter_id: Optional[str] = Query(None, description="Filter lessons by chapter ID"),
    q: Optional[str] = Query(None, min_length=1, description="Search by title or summary"),
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load lessons.")


@router.post("/", response_model=LessonNodeResponse, status_code=status.HTTP_201_CREATED)
def create_lesson(payload: LessonCreate, current_user=Depends(get_current_user)):
    """Create a lesson under a chapter."""
    del current_user
    try:
        return lesson_structure_service.create_lesson(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create lesson: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create lesson.")


@router.get("/{lesson_id}", response_model=LessonNodeResponse, status_code=status.HTTP_200_OK)
def get_lesson(lesson_id: str, current_user=Depends(get_current_user)):
    """Get a single lesson."""
    del current_user
    try:
        return lesson_structure_service.get_lesson(lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to get lesson %s: %s", lesson_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load lesson.")


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
    del current_user
    try:
        return lesson_chunk_service.recommend_chunks(
            lesson_id=lesson_id,
            max_chunks=payload.max_chunks,
            selection_strategy=payload.selection_strategy,
            resource_ids=payload.resource_ids,
            metadata=payload.metadata,
        )
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
def get_recommended_chunks_for_lesson(lesson_id: str, current_user=Depends(get_current_user)):
    """Load previously frozen recommended chunks for a lesson."""
    del current_user
    try:
        return lesson_chunk_service.get_recommendation(lesson_id)
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
