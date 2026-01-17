from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from app.services.ai_service import generate_learning_path
from app.database.mongo import get_db

router = APIRouter(prefix="/learning-path", tags=["Learning Path"])

db = get_db()
paths_col = db["learning_paths"]

class LearningPathRequest(BaseModel):
    user_email: str
    goal: str
    level: str

@router.post("/generate")
def generate_path(data: LearningPathRequest):
    path = generate_learning_path(data.goal, data.level)

    record = {
        "user_email": data.user_email,
        "goal": data.goal,
        "level": data.level,
        "path": path,
        "created_at": datetime.now()
    }

    paths_col.insert_one(record)
    return record

@router.get("/by-user/{user_email}")
def get_paths_by_user(user_email: str):
    paths = list(paths_col.find(
        {"user_email": user_email},
        {"_id": 0}
    ))
    return paths
