from fastapi import FastAPI

from backend.app.api import auth, users, resources
from backend.app.api.ask import router as ask_router
from backend.app.api.learning_path_api import router as learning_path_router
from backend.app.api.progress_api import router as progress_router

app = FastAPI(title="AI Personalized Learning Path System")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(learning_path_router, prefix="/learning-path", tags=["Learning Path"])
app.include_router(resources.router, prefix="/resources", tags=["Resources"])
app.include_router(progress_router, prefix="/progress", tags=["Progress"])
app.include_router(ask_router, prefix="/ask", tags=["Ask AI"])

@app.get("/")
def root():
    return {"message": "Backend hệ thống cá nhân hóa lộ trình học tập"}
