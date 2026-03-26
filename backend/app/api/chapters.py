"""API routes for chapter management."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import ChapterCreate, ChapterListResponse, ChapterResponse
from backend.app.services.lesson_service import lesson_structure_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chapters", tags=["Chapters"])


@router.get("/", response_model=ChapterListResponse, status_code=status.HTTP_200_OK)
def list_chapters(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    subject_id: Optional[str] = Query(
        None, description="Filter chapters by subject ID"
    ),
    q: Optional[str] = Query(
        None, min_length=1, description="Search by title or description"
    ),
    topic: Optional[str] = Query(None, min_length=1),
    current_user=Depends(get_current_user),
):
    """List chapters with pagination and optional filters."""
    del current_user
    try:
        return lesson_structure_service.list_chapters_paginated(
            page=page,
            size=size,
            subject_id=subject_id,
            q=q,
            topic=topic,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to list chapters: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load chapters.",
        )


@router.get(
    "/{chapter_id}", response_model=ChapterResponse, status_code=status.HTTP_200_OK
)
def get_chapter(chapter_id: str, current_user=Depends(get_current_user)):
    """Get a single chapter."""
    del current_user
    try:
        return lesson_structure_service.get_chapter(chapter_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to get chapter %s: %s", chapter_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load chapter.",
        )


@router.post("/", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
def create_chapter(payload: ChapterCreate, current_user=Depends(get_current_user)):
    """Create a chapter under a subject."""
    del current_user
    try:
        return lesson_structure_service.create_chapter(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create chapter: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create chapter.",
        )
