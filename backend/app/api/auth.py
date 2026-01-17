from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from app.database.mongo import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])

db = get_db()
users_col = db["users"]

class RegisterRequest(BaseModel):
    user_email: str
    password: str

@router.post("/register")
def register(data: RegisterRequest):
    if users_col.find_one({"user_email": data.user_email}):
        return {"message": "User đã tồn tại"}

    users_col.insert_one({
        "user_email": data.user_email,
        "password": data.password,
        "created_at": datetime.now()
    })

    return {"message": "Đăng ký thành công"}

@router.post("/login")
def login(data: RegisterRequest):
    user = users_col.find_one({
        "user_email": data.user_email,
        "password": data.password
    })
    if not user:
        return {"message": "Sai thông tin đăng nhập"}

    return {"message": "Đăng nhập thành công"}
