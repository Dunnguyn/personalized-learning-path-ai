from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.services.progress_service import update_progress
from backend.app.services.learning_path_service import generate_learning_path
from backend.app.database.mongo import db

router = APIRouter(prefix="/ask", tags=["Ask AI"])
rag = RAGPipeline()


class AskRequest(BaseModel):
    user_id: int      # ✅ INT
    question: str
    goal: str
    level: str
    completed: list[str] = []


class AskResponse(BaseModel):
    answer: dict
    learning_path: List[str]


def detect_concept(question: str) -> str:
    q = question.lower()
    if "list" in q:
        return "Python List"
    if "dictionary" in q:
        return "Python Dictionary"
    if "loop" in q:
        return "Python Loop"
    return "General Python"


def get_concept_id(name: str):
    c = db.concepts.find_one({"concept_name": name})
    return c["concept_id"] if c else None


@router.post("/", response_model=AskResponse)
def ask_ai(request: AskRequest):

    # 1. RAG
    rag_result = rag.run(
        question=request.question,
        goal=request.goal,
        level=request.level,
        completed=request.completed
    )

    # 2. Update progress
    concept_name = detect_concept(request.question)
    concept_id = get_concept_id(concept_name)

    if concept_id:
        update_progress(
            user_id=request.user_id,
            concept_id=concept_id,
            success=True
        )

    # 3. Learning path
    lp = generate_learning_path(
        user_id=request.user_id,
        goal=request.goal,
        level=request.level
    )

    return {
        "answer": rag_result,
        "learning_path": lp["recommended_path"]
    }
