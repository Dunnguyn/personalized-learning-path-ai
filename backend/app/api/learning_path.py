from fastapi import APIRouter
from backend.app.services.learning_path_service import generate_learning_path

router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


@router.post("/generate")
def generate_learning_path_api(
    user_id: int,
    goal: str,
    level: str
):
    return generate_learning_path(
        user_id=user_id,
        goal=goal,
        level=level
    )
