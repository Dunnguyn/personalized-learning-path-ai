from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.app.services.learning_path_service import generate_learning_path
from backend.app.api.auth import get_current_user
from backend.app.api.schemas import LevelEnum, LearningPathResponse, LearningPathItemResponse

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


# =========================
# REQUEST SCHEMA
# =========================
class LearningPathRequest(BaseModel):
    user_id: int
    goal: str
    level: LevelEnum


# =========================
# API
# =========================
@router.post("/generate", response_model=LearningPathResponse)
def generate_learning_path_api(payload: LearningPathRequest, current_user=Depends(get_current_user)):
    """
    Generate learning path; ensure the authenticated user matches requested user_id
    """
    if current_user["user_id"] != payload.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    result = generate_learning_path(
        user_id=payload.user_id,
        goal=payload.goal,
        level=payload.level.value if hasattr(payload.level, "value") else payload.level
    )
    return result