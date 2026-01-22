from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict

from backend.app.api.progress import (
    update_progress,
    get_user_mastery
)

router = APIRouter()


class ProgressUpdateRequest(BaseModel):
    user_id: str
    concept: str
    success: bool


@router.post("/update")
def api_update_progress(request: ProgressUpdateRequest):
    return update_progress(
        user_id=request.user_id,
        concept=request.concept,
        success=request.success
    )


@router.get("/{user_id}")
def api_get_user_progress(user_id: str) -> Dict[str, float]:
    return get_user_mastery(user_id)
