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

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
import hashlib
import uuid

import os
import logging
import time
from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.api.schemas import UserResponse, UserRoleEnum
from backend.app.services.event_logging_service import event_logging_service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# CONFIG (from env)
# =========================
SECRET_KEY = os.getenv("SECRET_KEY") or "CHANGE_THIS_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

logger.info(
    f"Auth initialized: algorithm={ALGORITHM}, token_expire={ACCESS_TOKEN_EXPIRE_MINUTES}min"
)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

router = APIRouter(prefix="/auth", tags=["Auth"])


def _load_admin_emails() -> set[str]:
    raw_value = os.getenv("ADMIN_EMAILS", "")
    return {
        item.strip().lower()
        for item in raw_value.split(",")
        if item and item.strip()
    }


ADMIN_EMAILS = _load_admin_emails()


def _token_fingerprint(token: str) -> str:
    """Return a non-reversible fingerprint for token revocation storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_auth_indexes() -> None:
    """Create indexes for revoked tokens collection."""
    try:
        db = get_db()
        revoked = db.revoked_tokens
        revoked.create_index("token_fingerprint", unique=True)
        revoked.create_index("jti", sparse=True)
        revoked.create_index("expires_at", expireAfterSeconds=0)
    except Exception as exc:
        logger.warning("Failed to ensure auth indexes: %s", exc)


def _is_token_revoked(db, token: str, payload: dict) -> bool:
    """Check whether token has been revoked via logout endpoint."""
    conditions = [{"token_fingerprint": _token_fingerprint(token)}]
    jti = payload.get("jti")
    if jti:
        conditions.append({"jti": jti})

    revoked = db.revoked_tokens.find_one(
        {
            "$or": conditions,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        }
    )
    return revoked is not None


_ensure_auth_indexes()


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


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
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

    # Calculate expiry as Unix timestamp (seconds since epoch)
    expire_timestamp = int(time.time()) + int(expires_delta.total_seconds())
    to_encode.update({"exp": expire_timestamp, "jti": str(uuid.uuid4())})

    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.debug(
        f"Created JWT token for user: {data.get('sub')}, expires at: {expire_timestamp}"
    )

    return token


def resolve_user_role(user: dict | None) -> str:
    """Resolve the effective role for a user document."""
    if not user:
        return UserRoleEnum.learner.value

    explicit_role = str(user.get("role") or "").strip().lower()
    if explicit_role == UserRoleEnum.admin.value:
        return UserRoleEnum.admin.value

    email = str(user.get("email") or "").strip().lower()
    if email and email in ADMIN_EMAILS:
        return UserRoleEnum.admin.value

    if explicit_role == UserRoleEnum.learner.value:
        return UserRoleEnum.learner.value

    return UserRoleEnum.learner.value


def attach_effective_role(user: dict | None) -> dict | None:
    """Return a shallow copy of the user document with resolved role attached."""
    if not user:
        return user

    enriched_user = dict(user)
    enriched_user["role"] = resolve_user_role(user)
    return enriched_user


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
    logger.debug(f"Validating JWT token: {token[:20]}...")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        logger.debug(f"JWT decoded successfully, user_id: {user_id_str}")

        if not user_id_str:
            logger.warning("Token missing 'sub' claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        # Validate MongoDB ObjectId format
        try:
            user_id = ObjectId(user_id_str)
        except Exception as e:
            logger.warning(
                f"Invalid ObjectId format in token: {user_id_str}, error: {e}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

    except JWTError as e:
        logger.warning(f"JWT decode error: {e}, token={token[:30]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    # Lookup user by ObjectId
    db = get_db()
    try:
        if _is_token_revoked(db, token, payload):
            logger.warning("Rejected revoked token for user_id=%s", user_id_str)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

        user = db.users.find_one({"_id": user_id})

        if not user:
            logger.warning(f"User not found: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        logger.debug(f"User authenticated: {user.get('email')}")
        return attach_effective_role(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error looking up user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed",
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
    role: UserRoleEnum = Field(default=UserRoleEnum.learner, description="User role")


class SignupRequest(BaseModel):
    """Signup request payload."""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=6, description="User password")
    fullName: str = Field(
        ..., min_length=2, max_length=200, description="User full name"
    )


class SignupResponse(BaseModel):
    """Signup response with JWT token."""

    token: str = Field(..., description="JWT token")
    user: dict = Field(..., description="User information")


class LogoutResponse(BaseModel):
    """Logout response payload."""

    success: bool = True
    message: str = "Logged out successfully"


# =========================
# API
# =========================
@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
def signup(payload: SignupRequest):
    """
    User signup: Create new account with email + password, return JWT token.

    Pipeline:
    1. Check if user already exists
    2. Hash password
    3. Create new user in database
    4. Create JWT token
    5. Return token + user info

    Args:
        payload: SignupRequest with email, password, fullName

    Returns:
        SignupResponse with access_token and user data

    Raises:
        HTTPException(400): If user already exists
        HTTPException(500): If database error
    """
    logger.info(f"Signup attempt: email={payload.email}")

    try:
        db = get_db()

        # Check if user already exists (case-insensitive email)
        existing_user = db.users.find_one(
            {"email": {"$regex": f"^{payload.email}$", "$options": "i"}}
        )

        if existing_user:
            logger.warning(
                f"Signup failed: user already exists for email {payload.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Hash password
        hashed_password = hash_password(payload.password)

        role = (
            UserRoleEnum.admin.value
            if payload.email.strip().lower() in ADMIN_EMAILS
            else UserRoleEnum.learner.value
        )

        # Create new user document
        new_user = {
            "email": payload.email,
            "password": hashed_password,
            "name": payload.fullName,
            "level": "beginner",
            "role": role,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Insert into database
        result = db.users.insert_one(new_user)
        user_id = str(result.inserted_id)

        # Create JWT token
        access_token = create_access_token(data={"sub": user_id})

        logger.info(f"Signup successful: user={payload.email}, user_id={user_id}")

        user_response = {
            "user_id": user_id,
            "email": payload.email,
            "name": payload.fullName,
            "level": "beginner",
            "role": role,
            "created_at": new_user["created_at"].isoformat(),
        }

        return SignupResponse(token=access_token, user=user_response)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Signup failed"
        )


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
        user = db.users.find_one(
            {"email": {"$regex": f"^{payload.email}$", "$options": "i"}}
        )

        if not user:
            logger.warning(f"Login failed: user not found for email {payload.email}")
            event_logging_service.log_event(
                "api_failed",
                success=False,
                error_code="INVALID_CREDENTIALS",
                metadata={"action": "login", "email": payload.email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Verify password
        if not verify_password(payload.password, user.get("password", "")):
            logger.warning(f"Login failed: invalid password for email {payload.email}")
            event_logging_service.log_event(
                "api_failed",
                user_id=str(user.get("_id")),
                success=False,
                error_code="INVALID_CREDENTIALS",
                metadata={"action": "login", "email": payload.email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Create JWT token
        access_token = create_access_token(data={"sub": str(user["_id"])})

        logger.info(
            f"Login successful: user={user.get('email')}, user_id={user['_id']}"
        )
        event_logging_service.log_event(
            "user_login",
            user_id=str(user.get("_id")),
            success=True,
            metadata={"email": user.get("email")},
        )

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=str(user["_id"]),
            email=user["email"],
            name=user["name"],
            role=resolve_user_role(user),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed"
        )


def require_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that only allows admin users to proceed."""
    if resolve_user_role(current_user) != UserRoleEnum.admin.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required",
        )
    return attach_effective_role(current_user)


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout(
    token: str = Depends(oauth2_scheme), current_user: dict = Depends(get_current_user)
):
    """
    Revoke current JWT token so it cannot be used again.

    This endpoint supports true server-side logout for access tokens.
    """
    try:
        db = get_db()
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp_timestamp = payload.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            if exp_timestamp
            else datetime.now(timezone.utc)
        )

        revoked_document = {
            "user_id": str(current_user.get("_id")),
            "token_fingerprint": _token_fingerprint(token),
            "jti": payload.get("jti"),
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        }

        db.revoked_tokens.update_one(
            {"token_fingerprint": revoked_document["token_fingerprint"]},
            {"$setOnInsert": revoked_document},
            upsert=True,
        )

        logger.info("Logout successful: user_id=%s", current_user.get("_id"))
        event_logging_service.log_event(
            "api_called",
            user_id=str(current_user.get("_id")),
            success=True,
            metadata={"action": "logout"},
        )
        return LogoutResponse(success=True, message="Logged out successfully")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Logout failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed",
        )
