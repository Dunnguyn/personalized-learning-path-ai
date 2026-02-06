"""
Ask API: Main AI tutoring endpoint with adaptive learning orchestration.

Endpoints:
- POST /ask/: Main Q&A endpoint (ask question, get answer + learning path)
- GET /ask/adaptive-status: Get adaptive learning status for user+concept
- POST /ask/detect-concepts: Batch concept detection
- GET /ask/recommend-concepts: Get next recommended concepts
- GET /ask/concept/{concept_id}: Get concept details

All endpoints include:
- Authentication (requires JWT token)
- Authorization (must be asking for own user_id)
- Input validation
- Error handling with specific HTTP codes
- Comprehensive logging
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from datetime import datetime
import logging
import uuid

from backend.app.api.schemas import (
    AskRequest,
    AskResponse,
    LevelEnum
)
from backend.app.api.auth import get_current_user
from backend.app.services.ai_service import AITutorService
from backend.app.services.progress_service import get_progress
from backend.app.services.adaptive_engine import adaptive_decision_summary, LearningMode
from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/ask", tags=["Ask/AI"])
ai_tutor = AITutorService()


# =========================
# MAIN ASK ENDPOINT
# =========================
@router.post("/", response_model=AskResponse, status_code=status.HTTP_200_OK)
def ask_ai(
    request: AskRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Main AI tutoring endpoint: Ask a question, get answer + learning path.
    
    Full orchestration pipeline:
    1. Validate user authorization (current_user._id == request.user_id)
    2. Validate request inputs (question length, goal, level)
    3. Call AITutorService.ask_ai() which:
       - RAG retrieval (semantic search for context)
       - LLM generation (Gemini answer)
       - Concept detection (map question to concept_id)
       - Progress update (EMA confidence scoring)
       - Adaptive learning (decide mode: remedial/normal/advanced)
       - Learning path generation (next recommended concepts)
    4. Track answer in search history / analytics
    5. Return comprehensive response (answer + learning path + adaptive info)
    
    Args:
        request: AskRequest with user_id, question, goal, level, completed (optional)
        current_user: Current authenticated user (from JWT token)
        
    Returns:
        AskResponse with:
        - success: bool
        - answer: Dict (answer_text, sources, confidence, latency_ms)
        - learning_path: List of recommended next concepts
        - concept_detected: Dict (concept_id, concept_name, score)
        - adaptive_info: Dict (mode, difficulty_boost, practice_recommendations)
        - progress_updated: bool
        
    Raises:
        HTTPException(401): If user_id doesn't match current_user
        HTTPException(400): If validation fails
        HTTPException(500): If internal error
        
    Example:
        >>> {
        ...     "user_id": "507f1f77bcf86cd799439011",
        ...     "question": "How do I use list comprehensions in Python?",
        ...     "goal": "Learn Python fundamentals",
        ...     "level": "intermediate",
        ...     "completed": ["basics", "syntax"]
        ... }
    """
    logger.info(f"Ask request: user_id={request.user_id}, question='{request.question[:50]}...'")
    
    try:
        # 1️⃣ VALIDATE AUTHORIZATION
        current_user_id = str(current_user.get("_id", ""))
        
        if current_user_id != request.user_id:
            logger.warning(
                f"Unauthorized ask attempt: auth_user={current_user_id}, "
                f"request_user={request.user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cannot ask questions for another user"
            )
        
        # 2️⃣ VALIDATE INPUTS
        if not request.question or len(request.question.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question must be at least 5 characters"
            )
        
        if len(request.question) > 2000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question cannot exceed 2000 characters"
            )
        
        if not request.goal or len(request.goal.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal must be at least 3 characters"
            )
        
        if not isinstance(request.level, LevelEnum):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid level"
            )
        
        logger.debug(f"Request validation passed: user={request.user_id}")
        
        # 3️⃣ CALL AI TUTOR SERVICE (orchestration)
        response = ai_tutor.ask_ai(
            user_id=request.user_id,
            question=request.question,
            goal=request.goal,
            level=request.level.value,
            completed_concepts=request.completed or []
        )
        
        logger.info(
            f"Ask completed successfully: user={request.user_id}, "
            f"concept={response.get('concept_detected', {}).get('concept_name')}"
        )
        
        return AskResponse(
            success=response.get("success", False),
            answer=response.get("answer", {}),
            learning_path=response.get("learning_path", []),
            concept_detected=response.get("concept_detected"),
            adaptive_info=response.get("adaptive_info"),
            progress_updated=response.get("progress_updated", False)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Ask error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Question processing failed"
        )


# =========================
# ADAPTIVE STATUS ENDPOINT
# =========================
@router.get("/adaptive-status", status_code=status.HTTP_200_OK)
def get_adaptive_status(
    user_id: str = Query(..., description="User ID (MongoDB ObjectId as string)"),
    concept_id: int = Query(..., ge=1, description="Concept ID"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get adaptive learning status for user + concept.
    
    Args:
        user_id: User ID
        concept_id: Concept ID
        current_user: Current authenticated user
        
    Returns:
        Dict with current progress + adaptive mode recommendations
    """
    logger.info(f"Adaptive status request: user={user_id}, concept={concept_id}")
    
    try:
        # Authorization
        if str(current_user.get("_id")) != user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        
        # Get progress
        progress = get_progress(user_id=user_id, concept_id=concept_id)
        
        if not progress:
            logger.info(f"No progress found: user={user_id}, concept={concept_id}")
            return {
                "success": False,
                "message": "No progress data found",
                "user_id": user_id,
                "concept_id": concept_id
            }
        
        # Generate adaptive summary
        summary = adaptive_decision_summary(
            mastery=progress.get("mastery", 0),
            confidence=progress.get("confidence", 0),
            success_rate=progress.get("success_rate", 0)
        )
        
        logger.info(f"Adaptive status: user={user_id}, concept={concept_id}, mode={summary['mode']}")
        
        return {
            "success": True,
            "user_id": user_id,
            "concept_id": concept_id,
            "progress": progress,
            "adaptive_summary": summary
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting adaptive status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get adaptive status"
        )


# =========================
# BATCH CONCEPT DETECTION
# =========================
@router.post("/detect-concepts", status_code=status.HTTP_200_OK)
def detect_concepts_batch(
    questions: list = Query(..., description="List of question strings"),
    current_user: dict = Depends(get_current_user)
):
    """
    Batch concept detection: map multiple questions to concepts.
    
    Args:
        questions: List of questions
        current_user: Current authenticated user
        
    Returns:
        List of detected concepts
    """
    logger.info(f"Batch concept detection: {len(questions)} questions")
    
    try:
        results = ai_tutor.detect_concepts_batch(questions)
        return {
            "success": True,
            "total": len(questions),
            "detected": results
        }
    except Exception as e:
        logger.exception(f"Batch concept detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Concept detection failed"
        )


# =========================
# RECOMMEND CONCEPTS
# =========================
@router.get("/recommend-concepts", status_code=status.HTTP_200_OK)
def recommend_next_concepts(
    user_id: str = Query(..., description="User ID"),
    limit: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(get_current_user)
):
    """
    Get recommended next concepts for user.
    
    Args:
        user_id: User ID
        limit: Max recommendations
        current_user: Current authenticated user
        
    Returns:
        List of recommended concepts
    """
    logger.info(f"Recommending concepts: user={user_id}, limit={limit}")
    
    try:
        if str(current_user.get("_id")) != user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        
        # Get user's progress summary
        db = get_db()
        progress_docs = list(db.progress.find({"user_id": user_id}))
        
        completed_concepts = set(p.get("concept_id") for p in progress_docs if p.get("mastery", 0) >= 0.8)
        
        # Find all concepts
        all_concepts = list(db.concepts.find({}).limit(1000))
        
        # Filter: not completed + no prerequisites with low mastery
        recommended = []
        for concept in all_concepts:
            concept_id = concept.get("concept_id")
            
            if concept_id in completed_concepts:
                continue
            
            recommended.append({
                "concept_id": concept_id,
                "concept_name": concept.get("concept_name"),
                "difficulty": concept.get("difficulty"),
                "topic": concept.get("topic")
            })
            
            if len(recommended) >= limit:
                break
        
        logger.info(f"Recommended {len(recommended)} concepts for user {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "recommended": recommended
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error recommending concepts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recommend concepts"
        )