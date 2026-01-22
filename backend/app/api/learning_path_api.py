from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict

from backend.app.api.progress import (
    update_progress,
    get_user_mastery
)

router = APIRouter()


# ===== REQUEST SCHEMA =====
class ProgressUpdateRequest(BaseModel):
    user_id: str
    concept: str
    success: bool


# ===== API: UPDATE PROGRESS =====
@router.post("/update")
def api_update_progress(request: ProgressUpdateRequest):
    return update_progress(
        user_id=request.user_id,
        concept=request.concept,
        success=request.success
    )


# ===== API: GET USER PROGRESS =====
@router.get("/{user_id}")
def api_get_user_progress(user_id: str) -> Dict[str, float]:
    return get_user_mastery(user_id)
