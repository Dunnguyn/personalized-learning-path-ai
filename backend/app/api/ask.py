from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional

from backend.app.api.schemas import AskRequest, AskResponse
from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.services.learning_path_service import generate_learning_path
from backend.app.services.confidence_scorer import score_confidence
from backend.app.services.progress_service import update_progress_with_confidence
from backend.app.database.mongo import db
from backend.app.api.auth import get_current_user

import logging

logger = logging.getLogger(__name__)

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/ask", tags=["Ask AI"])
rag = RAGPipeline()


# =========================
# HELPER: CONCEPT MATCHING
# =========================
def detect_concept_id_from_goal(goal: str) -> Optional[int]:
    """
    Map goal/topic → concept_id (safe & DB-driven)
    """
    concept = db.concepts.find_one(
        {"topic": {"$regex": goal, "$options": "i"}},
        {"concept_id": 1}
    )
    return concept["concept_id"] if concept else None


# =========================
# API ENDPOINT
# =========================
@router.post("/", response_model=AskResponse)
def ask_ai(request: AskRequest, current_user=Depends(get_current_user)):
    """
    AI Tutor endpoint:
    - Answer question using RAG
    - Score learner confidence
    - Update learning progress
    - Suggest adaptive learning path
    Requires authenticated user and ownership.
    """
    # Ownership check
    if current_user["user_id"] != request.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Basic input validation
    if not request.question or len(request.question.strip()) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question is required")
    if len(request.question) > 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question too long (max 2000 chars)")

    # 1. RAG ANSWER
    rag_result = rag.run(
        question=request.question,
        goal=request.goal,
        level=request.level.value if hasattr(request.level, "value") else request.level,
        completed=request.completed or []
    )

    answer_text = rag_result.get("answer", "")

    # 2. CONFIDENCE SCORING
    confidence = score_confidence(
        question=request.question,
        answer=answer_text
    )

    # 3. UPDATE PROGRESS (SAFE)
    concept_id = detect_concept_id_from_goal(request.goal)
    progress_updated = False

    if concept_id is not None:
        try:
            update_progress_with_confidence(
                user_id=request.user_id,
                concept_id=concept_id,
                confidence=confidence
            )
            progress_updated = True
        except Exception as e:
            logger.exception("Error updating progress: %s", e)

    # 4. ADAPTIVE LEARNING PATH
    learning_path = []

    if progress_updated:
        try:
            path_result = generate_learning_path(
                user_id=request.user_id,
                goal=request.goal,
                level=request.level.value if hasattr(request.level, "value") else request.level
            )
            learning_path = path_result.get("recommended_path", [])
        except Exception as e:
            logger.exception("Error generating learning path: %s", e)

    # 5. RESPONSE
    return {
        "answer": {
            "text": answer_text,
            "confidence": round(confidence, 3),
            "sources": rag_result.get("sources", [])
        },
        "learning_path": learning_path
    }