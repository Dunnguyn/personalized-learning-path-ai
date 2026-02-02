from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.api.progress import update_progress
from backend.app.api.learning_path import generate_learning_path


# ===== ROUTER (⚠️ PHẢI Ở TRÊN CÙNG) =====
router = APIRouter()
rag = RAGPipeline()


# ===== REQUEST SCHEMA =====
class AskRequest(BaseModel):
    user_id: str
    question: str
    goal: str
    level: str
    completed: Optional[List[str]] = []


# ===== RESPONSE SCHEMA =====
class AskResponse(BaseModel):
    answer: dict
    learning_path: List[str]


# ===== SIMPLE CONCEPT DETECTION =====
def detect_concept(question: str) -> str:
    q = question.lower()
    if "list" in q:
        return "Python List"
    if "dictionary" in q or "dict" in q:
        return "Python Dictionary"
    if "loop" in q:
        return "Python Loop"
    return "General Python"


# ===== API ENDPOINT =====
@router.post("/ask", response_model=AskResponse)
def ask_ai(request: AskRequest):
    """
    API trung tâm của hệ thống AI (RAG + Progress + Learning Path)
    """

    # 1. RAG
    rag_result = rag.run(
        question=request.question,
        goal=request.goal,
        level=request.level,
        completed=request.completed
    )

    # 2. Update progress
    concept = detect_concept(request.question)
    update_progress(
        user_id=request.user_id,
        concept=concept,
        success=True
    )

    # 3. Generate learning path
    learning_path = generate_learning_path(
        goal=request.goal,
        level=request.level,
        completed_concepts=request.completed
    )

    return {
        "answer": rag_result,
        "learning_path": learning_path["recommended_path"]
    }
