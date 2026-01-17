from fastapi import FastAPI
from app.api import auth, users, learning_path, resources, progress

app = FastAPI(title="AI Personalized Learning Path System")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(learning_path.router)
app.include_router(resources.router)
app.include_router(progress.router)


@app.get("/")
def home():
    return {"message": "Backend hệ thống cá nhân hóa lộ trình học tập"}
