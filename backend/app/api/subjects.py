"""API routes for subject management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import SubjectCreate, SubjectResponse
from backend.app.services.lesson_service import lesson_structure_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subjects", tags=["Subjects"])


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create subject.")
