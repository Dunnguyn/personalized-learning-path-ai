from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.post("/login")
def login(email: str, password: str):
    # Demo login
    if email == "test@gmail.com" and password == "123456":
        return {"token": "fake-jwt-token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")
