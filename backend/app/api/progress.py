from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from app.database.mongo import get_db

router = APIRouter(prefix="/progress", tags=["Progress"])

db = get_db()
progress_col = db["progress"]

class ProgressRequest(BaseModel):
    user_email: str
    concept: str
    completed: bool

@router.post("/update")
def update_progress(data: ProgressRequest):
    progress_col.update_one(
        {
            "user_email": data.user_email,
            "concept": data.concept
        },
        {
            "$set": {
                "completed": data.completed,
                "updated_at": datetime.now()
            }
        },
        upsert=True
    )

    return {"message": "Cập nhật tiến độ thành công"}

@router.get("/by-user/{user_email}")
def get_progress_by_user(user_email: str):
    progress = list(progress_col.find(
        {"user_email": user_email},
        {"_id": 0}
    ))
    return progress
