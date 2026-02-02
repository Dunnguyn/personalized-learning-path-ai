from fastapi import APIRouter
from pydantic import BaseModel
from backend.app.database.mongo import db
from backend.app.utils.counter import get_next_user_id


router = APIRouter()

class UserCreate(BaseModel):
    name: str
    email: str
    level: str

@router.post("/")
def create_user(user: UserCreate):
    user_id = get_next_user_id()

    db.users.insert_one({
        "user_id": user_id,
        "name": user.name,
        "email": user.email,
        "level": user.level
    })

    return {
        "user_id": user_id,
        "message": "User created successfully"
    }
