"""
Authentication Service: JWT token generation, user authentication, password verification.

Features:
- Email + password login
- JWT token generation + validation
- Password hashing (Argon2)
- User lookup by email
- Current user dependency for protected routes

All operations include:
- Comprehensive logging
- Error handling with specific HTTP codes
- Environment-based configuration
- Type hints + docstrings
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer

import os
import logging
from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.api.schemas import UserResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# CONFIG (from env)
# =========================
SECRET_KEY = os.getenv("SECRET_KEY") or "CHANGE_THIS_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

logger.info(f"Auth initialized: algorithm={ALGORITHM}, token_expire={ACCESS_TOKEN_EXPIRE_MINUTES}min")

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["Auth"])


# =========================
# UTILS
# =========================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify plain password against hashed password (Argon2).
    
    Args:
        plain_password: Plain text password from user
        hashed_password: Hashed password from DB
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.debug(f"Password verification error: {e}")
        return False


def hash_password(plain_password: str) -> str:
    """
    Hash password using Argon2.
    
    Args:
        plain_password: Plain text password
        
    Returns:
        Hashed password
    """
    return pwd_context.hash(plain_password)


def create_access_token(
    data: dict,
    expires_delta: timedelta = None
) -> str:
    """
    Create JWT access token.
    
    Args:
        data: Dict to encode (typically {"sub": user_id})
        expires_delta: Optional custom expiry duration
        
    Returns:
        JWT token string
        
    Example:
        >>> token = create_access_token({"sub": "507f1f77bcf86cd799439011"})
    """
    to_encode = data.copy()
    
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire.isoformat()})
    
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.debug(f"Created JWT token for user: {data.get('sub')}")
    
    return token


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Dependency: Extract and validate current user from JWT token.
    
    Used in protected routes to require authentication.
    
    Args:
        token: JWT token from Authorization header
        
    Returns:
        User document from DB (with _id, email, name, level, created_at, etc.)
        
    Raises:
        HTTPException(401): If token invalid or user not found
        
    Example:
        >>> @router.get("/profile")
        >>> def get_profile(current_user: dict = Depends(get_current_user)):
        ...     return current_user
    """
    logger.debug("Validating JWT token...")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        
        if not user_id_str:
            logger.warning("Token missing 'sub' claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        # Validate MongoDB ObjectId format
        try:
            user_id = ObjectId(user_id_str)
        except Exception as e:
            logger.warning(f"Invalid ObjectId format in token: {user_id_str}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
    
    except JWTError as e:
        logger.debug(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    # Lookup user by ObjectId
    db = get_db()
    try:
        user = db.users.find_one({"_id": user_id})
        
        if not user:
            logger.warning(f"User not found: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        logger.debug(f"User authenticated: {user.get('email')}")
        return user
    
    except Exception as e:
        logger.exception(f"Error looking up user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


# =========================
# SCHEMAS
# =========================
class LoginRequest(BaseModel):
    """Login request payload."""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=1, description="User password")


class LoginResponse(BaseModel):
    """Login response with JWT token."""
    access_token: str = Field(..., description="JWT token")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    email: EmailStr
    name: str = Field(..., description="User full name")


# =========================
# API
# =========================
@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest):
    """
    User login: Authenticate by email + password, return JWT token.
    
    Pipeline:
    1. Lookup user by email (case-insensitive)
    2. Verify password hash
    3. Create JWT token
    4. Return token + user info
    
    Args:
        payload: LoginRequest with email + password
        
    Returns:
        LoginResponse with access_token, token_type, user_id, email, name
        
    Raises:
        HTTPException(401): If email not found or password incorrect
        HTTPException(500): If DB error
        
    Example:
        >>> # Request
        >>> {
        ...     "email": "user@example.com",
        ...     "password": "securepassword123"
        ... }
        >>> # Response
        >>> {
        ...     "access_token": "eyJhbGci...",
        ...     "token_type": "bearer",
        ...     "user_id": "507f1f77bcf86cd799439011",
        ...     "email": "user@example.com",
        ...     "name": "John Doe"
        ... }
    """
    logger.info(f"Login attempt: email={payload.email}")
    
    try:
        db = get_db()
        
        # Lookup user by email (case-insensitive)
        user = db.users.find_one({
            "email": {"$regex": f"^{payload.email}$", "$options": "i"}
        })
        
        if not user:
            logger.warning(f"Login failed: user not found for email {payload.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Verify password
        if not verify_password(payload.password, user.get("password", "")):
            logger.warning(f"Login failed: invalid password for email {payload.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Create JWT token
        access_token = create_access_token(
            data={"sub": str(user["_id"])}
        )
        
        logger.info(f"Login successful: user={user.get('email')}, user_id={user['_id']}")
        
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=str(user["_id"]),
            email=user["email"],
            name=user["name"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )