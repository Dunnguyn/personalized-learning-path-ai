"""
Users API: User registration and profile management.

Endpoints:
- POST /users/: Create new user (register)
- GET /users/me: Get current user profile
- PUT /users/{user_id}: Update user profile

Features:
- Email uniqueness check (case-insensitive)
- Password hashing (Argon2)
- Level validation (enum)
- Email normalization
- Error handling with specific HTTP codes
- Comprehensive logging

All operations include:
- Input validation
- Error handling (duplicate email, invalid level, etc.)
- Logging at all levels
- Type hints + docstrings
"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime, timezone
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from bson import ObjectId
import logging

from backend.app.database.mongo import get_db
from backend.app.api.schemas import UserCreate, UserResponse, LevelEnum
from backend.app.api.auth import get_current_user
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/users", tags=["Users"])

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# =========================
# HELPERS
# =========================
def hash_password(password: str) -> str:
    """Hash password using Argon2."""
    return pwd_context.hash(password)


def _validate_create_input(user: UserCreate) -> None:
    """
    Validate UserCreate input.

    Args:
        user: UserCreate schema

    Raises:
        ValueError: If validation fails
    """
    if not user.name or not user.name.strip():
        raise ValueError("Name cannot be empty")

    if len(user.name.strip()) < 2:
        raise ValueError("Name must be at least 2 characters")

    if len(user.name.strip()) > 200:
        raise ValueError("Name cannot exceed 200 characters")

    if not user.password or len(user.password) < 8:
        raise ValueError("Password must be at least 8 characters")

    if user.level not in [
        LevelEnum.beginner,
        LevelEnum.intermediate,
        LevelEnum.advanced,
    ]:
        raise ValueError(f"Invalid level: {user.level}")


# =========================
# API
# =========================
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate):
    """
    Create a new user (register).

    Pipeline:
    1. Validate input
    2. Normalize email (lowercase)
    3. Check for duplicate email
    4. Hash password (Argon2)
    5. Create user document with MongoDB ObjectId (_id)
    6. Return user info (without password)

    Args:
        user: UserCreate with name, email, password, level

    Returns:
        UserResponse with user_id (MongoDB ObjectId as string), name, email, level, created_at

    Raises:
        HTTPException(400): If validation fails or email already exists
        HTTPException(500): If database error

    Example:
        >>> {
        ...     "name": "John Doe",
        ...     "email": "john@example.com",
        ...     "password": "securepassword123",
        ...     "level": "beginner"
        ... }
    """
    logger.info(f"Creating user: name={user.name}, email={user.email}")

    try:
        # 1️⃣ VALIDATE INPUT
        _validate_create_input(user)

        # 2️⃣ NORMALIZE EMAIL
        email = user.email.lower().strip()
        logger.debug(f"Normalized email: {email}")

        # 3️⃣ CHECK DUPLICATE (case-insensitive)
        db = get_db()
        existing = db.users.find_one(
            {"email": {"$regex": f"^{email}$", "$options": "i"}}
        )

        if existing:
            logger.warning(f"Duplicate email: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
            )

        # 4️⃣ HASH PASSWORD
        hashed_password = hash_password(user.password)

        # 5️⃣ CREATE USER DOCUMENT
        # MongoDB will auto-generate _id as ObjectId
        doc = {
            "name": user.name.strip(),
            "email": email,
            "password": hashed_password,
            "level": (
                user.level.value if isinstance(user.level, LevelEnum) else user.level
            ),
            "created_at": datetime.now(timezone.utc),
            "is_active": True,
        }

        result = db.users.insert_one(doc)
        user_id = str(result.inserted_id)

        logger.info(f"User created successfully: user_id={user_id}, email={email}")

        return UserResponse(
            user_id=user_id,
            name=doc["name"],
            email=doc["email"],
            level=doc["level"],
            learning_goal=doc.get("learning_goal"),
            created_at=doc["created_at"],
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except DuplicateKeyError:
        logger.warning(f"Duplicate key error for email: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
        )
    except Exception as e:
        logger.exception(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user",
        )


# =========================
# GET CURRENT USER
# =========================
@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user's profile.

    Args:
        current_user: Current user from JWT token

    Returns:
        UserResponse with user info
    """
    try:
        return UserResponse(
            user_id=str(current_user["_id"]),
            name=current_user["name"],
            email=current_user["email"],
            level=current_user.get("level", "beginner"),
            learning_goal=current_user.get("learning_goal"),
            created_at=current_user["created_at"],
        )
    except Exception as e:
        logger.exception(f"Error getting user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not get user profile",
        )


# =========================
# UPDATE USER
# =========================
class UserUpdate(BaseModel):
    """User update payload."""

    level: LevelEnum = Field(None, description="User level")
    learning_goal: str = Field(None, description="Learning goal")


@router.put("/{user_id}", status_code=status.HTTP_200_OK)
def update_user(
    user_id: str,
    update_data: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """
    Update user profile (level, learning goal, etc.).

    Args:
        user_id: User ID to update
        update_data: UserUpdate with level and learning_goal
        current_user: Current authenticated user

    Returns:
        Updated user info

    Raises:
        HTTPException(403): If trying to update another user
        HTTPException(404): If user not found
        HTTPException(500): If database error
    """
    # Check authorization
    if str(current_user["_id"]) != user_id:
        logger.warning(
            f"Unauthorized update attempt: {current_user['_id']} trying to update {user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update another user's profile",
        )

    try:
        db = get_db()

        # Build update document
        update_doc = {}
        if update_data.level:
            update_doc["level"] = (
                update_data.level.value
                if isinstance(update_data.level, LevelEnum)
                else update_data.level
            )
        if update_data.learning_goal:
            update_doc["learning_goal"] = update_data.learning_goal

        update_doc["updated_at"] = datetime.now(timezone.utc)

        # Update user
        result = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_doc})

        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Get updated user
        updated_user = db.users.find_one({"_id": ObjectId(user_id)})

        logger.info(f"User updated: user_id={user_id}, updates={update_doc}")

        return {"success": True, "user_id": user_id, "updated_fields": update_doc}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update user",
        )
