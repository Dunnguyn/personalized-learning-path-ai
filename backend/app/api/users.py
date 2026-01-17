from fastapi import APIRouter
from app.database.mongo import get_db

router = APIRouter(prefix="/users", tags=["Users"])

db = get_db()
users_col = db["users"]

@router.get("/{user_email}")
def get_user(user_email: str):
    user = users_col.find_one(
        {"user_email": user_email},
        {"_id": 0, "password": 0}
    )
    return user
