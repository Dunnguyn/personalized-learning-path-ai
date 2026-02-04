from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.app.services.learning_path_service import generate_learning_path

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
    level: str


# =========================
# RESPONSE SCHEMAS
# =========================
class LearningPathItemResponse(BaseModel):
    concept_id: int
    concept_name: str
    difficulty: int
    bloom_level: Optional[str]
    mode: str
    priority_score: float
    resources: list


class LearningPathResponse(BaseModel):
    path_id: str
    user_id: int
    goal: str
    level: str
    generated_at: datetime
    recommended_path: List[LearningPathItemResponse]


# =========================
# API
# =========================
@router.post("/generate", response_model=LearningPathResponse)
def generate_learning_path_api(payload: LearningPathRequest):
    """
    Sinh learning path dựa trên:
    - goal
    - level
    - progress + prerequisite
    """

    result = generate_learning_path(
        user_id=payload.user_id,
        goal=payload.goal,
        level=payload.level
    )
    return result
