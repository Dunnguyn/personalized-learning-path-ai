"""API routes for subject management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import SubjectCreate, SubjectListResponse, SubjectResponse
from backend.app.services.lesson_service import lesson_structure_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subjects", tags=["Subjects"])


@router.get("/", response_model=SubjectListResponse, status_code=status.HTTP_200_OK)
def list_subjects(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = Query(
        None, min_length=1, description="Search by title, slug, or description"
    ),
    topic: str | None = Query(None, min_length=1),
    level: str | None = Query(None, min_length=1),
    current_user=Depends(get_current_user),
):
    """List subjects with pagination and optional filters."""
    del current_user
    try:
        return lesson_structure_service.list_subjects_paginated(
            page=page,
            size=size,
            q=q,
            topic=topic,
            level=level,
        )
    except Exception as exc:
        logger.exception("Failed to list subjects: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load subjects.",
        )


@router.get(
    "/{subject_id}", response_model=SubjectResponse, status_code=status.HTTP_200_OK
)
def get_subject(subject_id: str, current_user=Depends(get_current_user)):
    """Get a single subject."""
    del current_user
    try:
        return lesson_structure_service.get_subject(subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to get subject %s: %s", subject_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load subject.",
        )


@router.post("/", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, current_user=Depends(get_current_user)):
    """Create a subject."""
    del current_user
    try:
        return lesson_structure_service.create_subject(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create subject: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create subject.",
        )
