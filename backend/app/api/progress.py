from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime

from backend.app.services.progress_service import update_progress_with_confidence
from backend.app.api.auth import get_current_user
from backend.app.api.schemas import ProgressUpdate, ProgressUpdateResponse

router = APIRouter(prefix="/progress", tags=["Progress"])


# =========================
# API
# =========================
@router.post("/update", response_model=ProgressUpdateResponse)
def update_progress_api(payload: ProgressUpdate, current_user=Depends(get_current_user)):
    """
    Update learning progress: requires authenticated user and ownership
    """
    if current_user["user_id"] != payload.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    result = update_progress_with_confidence(
        user_id=payload.user_id,
        concept_id=payload.concept_id,
        mastery=payload.mastery,
        confidence=payload.confidence,
        total_attempts=payload.total_attempts
    )

    return result