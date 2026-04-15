"""Diagnostic onboarding endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    DiagnosticResultResponse,
    DiagnosticStartRequest,
    DiagnosticStartResponse,
    DiagnosticSubmitRequest,
)
from backend.app.services.learner_profile_service import learner_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostic", tags=["Diagnostic"])


@router.post("/start", response_model=DiagnosticStartResponse, status_code=status.HTTP_200_OK)
def start_diagnostic(
    payload: DiagnosticStartRequest, current_user=Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))
    try:
        result = learner_profile_service.start_diagnostic(
            user_id=user_id,
            subject_id=payload.subject_id or None,
            goal=payload.goal,
            max_questions=payload.max_questions,
        )
        return DiagnosticStartResponse(**result)
    except Exception as exc:
        logger.exception("Failed to start diagnostic: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not start diagnostic.",
        ) from exc


@router.post(
    "/submit", response_model=DiagnosticResultResponse, status_code=status.HTTP_200_OK
)
def submit_diagnostic(
    payload: DiagnosticSubmitRequest, current_user=Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))
    try:
        result = learner_profile_service.submit_diagnostic(
            user_id=user_id,
            session_id=payload.session_id,
            subject_id=payload.subject_id or None,
            answers=[item.model_dump() for item in payload.answers],
        )
        return DiagnosticResultResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to submit diagnostic: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit diagnostic.",
        ) from exc


@router.get("/result", response_model=DiagnosticResultResponse, status_code=status.HTTP_200_OK)
def get_diagnostic_result(
    subject_id: str | None = Query(None, description="Subject id to inspect"),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id", ""))
    try:
        result = learner_profile_service.get_diagnostic_result(
            user_id=user_id,
            subject_id=subject_id,
        )
        return DiagnosticResultResponse(**result)
    except Exception as exc:
        logger.exception("Failed to load diagnostic result: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load diagnostic result.",
        ) from exc
