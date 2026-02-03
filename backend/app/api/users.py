from fastapi import APIRouter, HTTPException
from datetime import datetime

from backend.app.database.mongo import db
from backend.app.utils.counter import get_next_user_id
from backend.app.api.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", response_model=UserResponse)
def create_user(user: UserCreate):
    """
    Tạo user mới cho hệ thống
    """

    # 1. Check email trùng
    if db.users.find_one({"email": user.email}):
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )

    # 2. Generate user_id (INT)
    user_id = get_next_user_id()

    doc = {
        "user_id": user_id,
        "name": user.name,
        "email": user.email,
        "level": user.level,
        "created_at": datetime.utcnow()
    }

    # 3. Insert DB
    db.users.insert_one(doc)

    # 4. Trả về đúng schema
    return doc
