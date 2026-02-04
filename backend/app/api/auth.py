from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from jose import jwt
from passlib.context import CryptContext

from backend.app.database.mongo import db

# =========================
# CONFIG
# =========================
SECRET_KEY = "CHANGE_THIS_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


router = APIRouter(prefix="/auth", tags=["Auth"])


# =========================
# UTILS
# =========================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# =========================
# SCHEMAS
# =========================
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: EmailStr


# =========================
# API
# =========================
@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    """
    Login chuẩn:
    - Check user trong DB
    - Verify password hash
    - Trả JWT token
    """

    user = db.users.find_one({"email": payload.email})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not verify_password(payload.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token(
        data={
            "sub": str(user["user_id"]),
            "email": user["email"]
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {
        "access_token": access_token,
        "user_id": user["user_id"],
        "email": user["email"]
    }
