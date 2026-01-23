from fastapi import FastAPI
from backend.app.api import auth, users, resources, learning_path, ask

app = FastAPI(title="AI Personalized Learning Path System")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(resources.router, prefix="/resources", tags=["Resources"])
app.include_router(learning_path.router)
app.include_router(ask.router)

@app.get("/")
def root():
    return {"message": "Backend hệ thống cá nhân hóa lộ trình học tập"}
