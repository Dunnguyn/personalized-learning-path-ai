from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from passlib.context import CryptContext
import logging

from backend.app.database.mongo import db
from backend.app.utils.counter import get_next_user_id
from backend.app.api.schemas import UserCreate, UserResponse, LevelEnum
from backend.app.api.auth import get_current_user
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

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
    Create a new user:
    - Hash password
    - Validate level via schema
    - Do not return password
    """
    # Normalize email
    email = user.email.lower()

    # Ensure uniqueness (DB unique index recommended)
    user_id = get_next_user_id()

    doc = {
        "user_id": user_id,
        "name": user.name,
        "email": email,
        "password": hash_password(user.password),
        "level": user.level.value if isinstance(user.level, LevelEnum) else user.level,
        "created_at": datetime.utcnow()
    }

    try:
        db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists")
    except Exception as e:
        logger.exception("Error inserting user: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create user")

    return {
        "user_id": user_id,
        "name": user.name,
        "email": email,
        "level": doc["level"],
        "created_at": doc["created_at"]
    }