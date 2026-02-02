from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.api.progress import update_progress
from backend.app.api.learning_path import generate_learning_path
from backend.app.database.mongo import db


# ===== ROUTER =====
router = APIRouter()
rag = RAGPipeline()


# ===== REQUEST SCHEMA =====
class AskRequest(BaseModel):
    user_id: int      # ✅ INT
    question: str
    goal: str
    level: str
    completed: list[str] = []


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


# ===== MAP CONCEPT NAME → CONCEPT_ID (THEO ERD) =====
def get_concept_id_by_name(concept_name: str) -> Optional[int]:
    concept = db.concepts.find_one(
        {"concept_name": concept_name},
        {"concept_id": 1}
    )
    return concept["concept_id"] if concept else None


# ===== API ENDPOINT =====
@router.post("/ask", response_model=AskResponse)
def ask_ai(request: AskRequest):
    """
    API trung tâm của hệ thống AI (RAG + Progress + Learning Path)
    """

    # ===== 1. RUN RAG PIPELINE =====
    rag_result = rag.run(
        question=request.question,
        goal=request.goal,
        level=request.level,
        completed=request.completed
    )

    # ===== 2. DETECT CONCEPT & UPDATE PROGRESS =====
    concept_name = detect_concept(request.question)
    concept_id = get_concept_id_by_name(concept_name)

    # Chỉ update progress nếu concept tồn tại trong DB
    if concept_id is not None:
        update_progress(
            user_id=request.user_id,
            concept_id=concept_id,
            success=True
        )

    # ===== 3. GENERATE LEARNING PATH =====
    learning_path = generate_learning_path(
        user_id=request.user_id,
        goal=request.goal,
        level=request.level
    )


    return {
        "answer": rag_result,
        "learning_path": learning_path["recommended_path"]
    }
