from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from backend.app.services.learning_path_service import generate_learning_path

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


# =========================
# SCHEMAS
# =========================
class LearningPathRequest(BaseModel):
    user_id: int
    goal: str
    level: str


class LearningPathResponse(BaseModel):
    recommended_path: List[str]


# =========================
# API
# =========================
@router.post("/generate", response_model=LearningPathResponse)
def generate_learning_path_api(request: LearningPathRequest):
    """
    Sinh learning path dựa trên:
    - goal
    - level
    - progress + prerequisite
    """

    return generate_learning_path(
        user_id=request.user_id,
        goal=request.goal,
        level=request.level
    )
