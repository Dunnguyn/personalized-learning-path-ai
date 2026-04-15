"""Learner profile endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    LearnerProfileResponse,
    LearnerProfileUpsertRequest,
)
from backend.app.services.learner_profile_service import learner_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learner-profile", tags=["Learner Profile"])


@router.get("/me", response_model=LearnerProfileResponse, status_code=status.HTTP_200_OK)
def get_my_learner_profile(current_user=Depends(get_current_user)):
    user_id = str(current_user.get("_id", ""))
    try:
        return LearnerProfileResponse(
            **learner_profile_service.initialize_profile(user_id)
        )
    except Exception as exc:
        logger.exception("Failed to load learner profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learner profile.",
        ) from exc


@router.put("/me", response_model=LearnerProfileResponse, status_code=status.HTTP_200_OK)
def update_my_learner_profile(
    payload: LearnerProfileUpsertRequest, current_user=Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))
    try:
        profile = learner_profile_service.update_profile(
            user_id, payload.model_dump(exclude_none=False)
        )
        return LearnerProfileResponse(**profile)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to update learner profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update learner profile.",
        ) from exc
