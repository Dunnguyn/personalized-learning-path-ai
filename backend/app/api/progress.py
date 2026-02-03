from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.services.progress_service import update_progress

router = APIRouter(prefix="/progress", tags=["Progress"])


# =========================
# SCHEMAS
# =========================
class ProgressUpdateRequest(BaseModel):
    user_id: int
    concept_id: int
    success: bool


class ProgressUpdateResponse(BaseModel):
    user_id: int
    concept_id: int
    mastery: float


# =========================
# API
# =========================
@router.post("/update", response_model=ProgressUpdateResponse)
def update_progress_api(request: ProgressUpdateRequest):
    """
    Update learning progress & mastery for a concept
    """

    mastery = update_progress(
        user_id=request.user_id,
        concept_id=request.concept_id,
        success=request.success
    )

    return {
        "user_id": request.user_id,
        "concept_id": request.concept_id,
        "mastery": mastery
    }
