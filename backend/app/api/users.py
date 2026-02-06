"""
Users API: User registration and profile management.

Endpoints:
- POST /users/: Create new user (register)

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

from fastapi import APIRouter, HTTPException, status
from datetime import datetime
from passlib.context import CryptContext
import logging

from backend.app.database.mongo import get_db
from backend.app.api.schemas import UserCreate, UserResponse, LevelEnum
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/users", tags=["Users"])

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


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
    
    if user.level not in [LevelEnum.beginner, LevelEnum.intermediate, LevelEnum.advanced]:
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
        existing = db.users.find_one({
            "email": {"$regex": f"^{email}$", "$options": "i"}
        })
        
        if existing:
            logger.warning(f"Duplicate email: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists"
            )
        
        # 4️⃣ HASH PASSWORD
        hashed_password = hash_password(user.password)
        
        # 5️⃣ CREATE USER DOCUMENT
        # MongoDB will auto-generate _id as ObjectId
        doc = {
            "name": user.name.strip(),
            "email": email,
            "password": hashed_password,
            "level": user.level.value if isinstance(user.level, LevelEnum) else user.level,
            "created_at": datetime.utcnow(),
            "is_active": True
        }
        
        result = db.users.insert_one(doc)
        user_id = str(result.inserted_id)
        
        logger.info(f"User created successfully: user_id={user_id}, email={email}")
        
        return UserResponse(
            user_id=user_id,
            name=doc["name"],
            email=doc["email"],
            level=doc["level"],
            created_at=doc["created_at"]
        )
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except DuplicateKeyError:
        logger.warning(f"Duplicate key error for email: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )
    except Exception as e:
        logger.exception(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user"
        )