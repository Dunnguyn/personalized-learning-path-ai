from fastapi import APIRouter
from backend.app.database.mongo import get_db
from backend.app.api.schemas import UserCreate

router = APIRouter()

@router.post("/", summary="Tạo người dùng mới")
def create_user(user: UserCreate):
    db = get_db()
    db.users.insert_one(user.dict())
    return {"message": "User created successfully"}
