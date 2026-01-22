from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.api.progress import update_progress
from backend.app.api.learning_path import generate_learning_path


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
    learning_path: List[dict]


# ===== SIMPLE CONCEPT DETECTION =====
def detect_concept(question: str) -> str:
    """
    Map đơn giản câu hỏi → concept (đủ dùng cho đề án)
    """
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

    # ===== 1. RUN RAG PIPELINE (⚠️ ĐÃ SỬA Ở ĐÂY) =====
    rag_result = rag.run(
        question=request.question,   # 🔥 FIX: truyền question
        goal=request.goal,
        level=request.level,
        completed=request.completed
    )

    # ===== 2. DETECT RELATED CONCEPT =====
    concept = detect_concept(request.question)

    # ===== 3. UPDATE LEARNING PROGRESS =====
    update_progress(
        user_id=request.user_id,
        concept=concept,
        success=True
    )

    # ===== 4. GENERATE LEARNING PATH =====
    learning_path = generate_learning_path(
        user_id=request.user_id,
        goal=request.goal
    )

    return {
        "answer": rag_result,
        "learning_path": learning_path
    }
