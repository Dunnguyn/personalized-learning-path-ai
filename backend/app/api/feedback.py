"""Feedback ingestion endpoint for explicit learner feedback."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.feedback_service import feedback_service

router = APIRouter(tags=["Feedback"])


class LearnerFeedbackRequest(BaseModel):
    feedback_type: str = Field(..., min_length=2, max_length=50)
    value: str = Field(..., min_length=1, max_length=500)
    path_id: Optional[str] = None
    lesson_id: Optional[str] = None
    concept_id: Optional[int] = None
    resource_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/feedback", status_code=200)
def submit_feedback(
    payload: LearnerFeedbackRequest, current_user=Depends(get_current_user)
):
    user_id = str(current_user.get("_id", ""))
    feedback = feedback_service.record_explicit_feedback(
        user_id=user_id,
        feedback_type=payload.feedback_type,
        value=payload.value,
        path_id=payload.path_id,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        metadata=payload.metadata,
    )

    event_logging_service.log_event(
        "learner_feedback_submitted",
        user_id=user_id,
        path_id=payload.path_id,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        success=True,
        metadata={
            "feedback_type": payload.feedback_type,
            "value": payload.value,
            **payload.metadata,
        },
    )

    return {
        "ok": True,
        "feedback_id": str(feedback.get("_id")),
        "feedback_type": payload.feedback_type,
    }
