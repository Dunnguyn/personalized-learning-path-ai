from fastapi import APIRouter, HTTPException, status
from datetime import datetime
from passlib.context import CryptContext

from backend.app.database.mongo import db
from backend.app.utils.counter import get_next_user_id
from backend.app.api.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate):
    """
    Tạo user mới cho hệ thống
    - Hash password
    - Không trả password về client
    """

    # 1. Check email trùng
    if db.users.find_one({"email": user.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )

    # 2. Generate user_id
    user_id = get_next_user_id()

    doc = {
        "user_id": user_id,
        "name": user.name,
        "email": user.email,
        "password": hash_password(user.password),
        "level": user.level,
        "created_at": datetime.utcnow()
    }

    db.users.insert_one(doc)

    return {
        "user_id": user_id,
        "name": user.name,
        "email": user.email,
        "level": user.level,
        "created_at": doc["created_at"]
    }
