from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import (
    auth,
    users,
    resources,
    learning_path,
    progress,
    ask,
    recommendations
)

# =========================
# INIT APP
# =========================
app = FastAPI(
    title="AI Personalized Learning Path System",
    description="Backend cho hệ thống cá nhân hóa lộ trình học tập sử dụng AI + RAG",
    version="1.0.0"
)

# =========================
# CORS MIDDLEWARE (cho frontend)
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Frontend dev server
        "http://localhost:3000",  # Alternative frontend port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# REGISTER ROUTERS
# =========================
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(learning_path.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")

# =========================
# ROOT ENDPOINT
# =========================
@app.get("/")
def root():
    return {
        "message": "Backend hệ thống cá nhân hóa lộ trình học tập",
        "status": "running"
    }
