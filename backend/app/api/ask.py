from fastapi import APIRouter
from typing import List

from backend.app.api.schemas import AskRequest, AskResponse
from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.services.progress_service import update_progress
from backend.app.services.learning_path_service import generate_learning_path
from backend.app.database.mongo import db

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/ask", tags=["Ask AI"])
rag = RAGPipeline()


# =========================
# HELPER FUNCTIONS
# =========================
def detect_concept(question: str) -> str:
    """
    Detect learning concept from question (simple heuristic).
    Sau này có thể thay bằng NLP / classifier.
    """
    q = question.lower()
    if "list" in q:
        return "Python List"
    if "dictionary" in q or "dict" in q:
        return "Python Dictionary"
    if "loop" in q:
        return "Python Loop"
    return "General Python"


def get_concept_id_by_name(concept_name: str) -> int | None:
    """
    Map concept_name -> concept_id từ DB
    """
    concept = db.concepts.find_one(
        {"concept_name": concept_name},
        {"concept_id": 1}
    )
    return concept["concept_id"] if concept else None


# =========================
# API ENDPOINT
# =========================
@router.post("/", response_model=AskResponse)
def ask_ai(request: AskRequest):
    """
    Core API:
    - RAG trả lời câu hỏi
    - Update progress
    - Gợi ý learning path
    """

    # ===== 1. RAG =====
    rag_result = rag.run(
        question=request.question,
        goal=request.goal,
        level=request.level,
        completed=request.completed
    )

    # ===== 2. UPDATE PROGRESS =====
    concept_name = detect_concept(request.question)
    concept_id = get_concept_id_by_name(concept_name)

    if concept_id is not None:
        update_progress(
            user_id=request.user_id,
            concept_id=concept_id,
            success=True
        )

    # ===== 3. LEARNING PATH =====
    learning_path = generate_learning_path(
        user_id=request.user_id,
        goal=request.goal,
        level=request.level
    )

    # ===== 4. RESPONSE =====
    return {
        "answer": rag_result,
        "learning_path": learning_path.get("recommended_path", [])
    }
