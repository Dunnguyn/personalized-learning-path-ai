from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI

from backend.app.api import (
    auth,
    users,
    resources,
    learning_path,
    progress,
    ask
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
# REGISTER ROUTERS
# =========================
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(resources.router)
app.include_router(learning_path.router)
app.include_router(progress.router)
app.include_router(ask.router)

# =========================
# ROOT ENDPOINT
# =========================
@app.get("/")
def root():
    return {
        "message": "Backend hệ thống cá nhân hóa lộ trình học tập",
        "status": "running"
    }
