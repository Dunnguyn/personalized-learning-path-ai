from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/auth", tags=["Auth"])


# =========================
# SCHEMAS
# =========================
class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str


# =========================
# API
# =========================
@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """
    Demo login API.
    Sau này thay bằng:
    - DB check
    - password hash
    - JWT thật
    """

    # ===== DEMO AUTH =====
    if request.email == "test@gmail.com" and request.password == "123456":
        return {"token": "fake-jwt-token"}

    raise HTTPException(
        status_code=401,
        detail="Invalid email or password"
    )
