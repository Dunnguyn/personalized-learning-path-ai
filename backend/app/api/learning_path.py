from fastapi import APIRouter
from backend.app.api.schemas import (
    LearningPathRequest,
    LearningPathResponse,
    ProgressUpdate
)
from backend.app.services.ai_service import generate_learning_path
from backend.app.api.progress import update_progress, get_user_mastery

router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


# ==================================================
# 1️⃣ GENERATE LEARNING PATH (RAG CORE)
# ==================================================
@router.post(
    "/generate",
    response_model=LearningPathResponse,
    summary="Sinh lộ trình học tập cá nhân hóa (RAG)"
)
def generate_path(data: LearningPathRequest):
    # Nếu có user_id → lấy mastery map
    completed = data.completed_concepts

    if data.user_id:
        mastery_map = get_user_mastery(data.user_id)
        completed = [k for k, v in mastery_map.items() if v >= 0.8]

    return generate_learning_path(
        goal=data.goal,
        level=data.level,
        completed_concepts=completed
    )


# ==================================================
# 2️⃣ UPDATE PROGRESS
# ==================================================
@router.post(
    "/update",
    summary="Cập nhật tiến độ học tập"
)
def update_learning_progress(data: ProgressUpdate):
    return update_progress(
        user_id=data.user_id,
        concept=data.concept,
        success=data.success
    )


# ==================================================
# 3️⃣ GET USER MASTERY MAP
# ==================================================
@router.get(
    "/{user_id}",
    summary="Lấy bản đồ mastery của người học"
)
def get_progress(user_id: str):
    return get_user_mastery(user_id)
