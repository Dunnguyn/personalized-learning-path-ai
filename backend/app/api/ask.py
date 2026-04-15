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

from fastapi import APIRouter, Body, HTTPException, status, Depends, Query
from datetime import datetime, timezone
import logging
import uuid

from backend.app.api.schemas import (
    AskRequest,
    AskResponse,
    AskAdaptiveStatusResponse,
    AskDetectConceptsRequest,
    AskDetectConceptsResponse,
    AskRecommendedConceptsResponse,
    AskHistoryResponse,
    BasicMessageResponse,
    LevelEnum,
)
from backend.app.api.auth import get_current_user
from backend.app.services.ai_tutor.service import AITutorService
from backend.app.services.progress_tracking.progress import get_progress
from backend.app.services.adaptive_engine import adaptive_decision_summary, LearningMode
from backend.app.database.mongo import get_db
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.feedback_service import feedback_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.unified_learning_path_service import learning_path_service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/ask", tags=["Ask/AI"])
ai_tutor = AITutorService()


# =========================
# HELPER FUNCTIONS
# =========================
def _scalar_request_value(value):
    """Accept enum-like values or plain scalars from request payloads."""
    if value is None:
        return None
    return getattr(value, "value", value)


def _save_ask_history(
    user_id: str,
    question: str,
    answer_text: str,
    goal: str,
    level: str,
    concept_id: int = None,
    concept_name: str = None,
    confidence: float = 0.0,
) -> None:
    """
    Save question and answer to user's ask history.

    Args:
        user_id: MongoDB ObjectId as string
        question: User's question
        answer_text: AI's answer
        goal: Learning goal
        level: User's level
        concept_id: Detected concept ID
        concept_name: Detected concept name
        confidence: Answer confidence score
    """
    try:
        db = get_db()
        db.ask_history.insert_one(
            {
                "user_id": user_id,
                "question": question,
                "answer": answer_text,
                "goal": goal,
                "level": level,
                "concept_id": concept_id,
                "concept_name": concept_name,
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc),
            }
        )
        logger.debug(
            f"Saved ask history: user={user_id}, question='{question[:50]}...'"
        )
    except Exception as e:
        logger.warning(f"Failed to save ask history: {e}")


def _get_ask_history(
    user_id: str, limit: int = 50, skip: int = 0, goal: str = None
) -> list:
    """
    Get user's question history.

    Args:
        user_id: MongoDB ObjectId as string
        limit: Maximum number of records to return
        skip: Number of records to skip (for pagination)
        goal: Optional filter by learning goal

    Returns:
        List of history records
    """
    try:
        db = get_db()

        # Build query
        query = {"user_id": user_id}
        if goal:
            query["goal"] = goal

        # Get total count
        total = db.ask_history.count_documents(query)

        # Get records sorted by newest first
        records = list(
            db.ask_history.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        )

        # Convert ObjectId to string
        for record in records:
            record["_id"] = str(record["_id"])
            record["timestamp"] = record["timestamp"].isoformat()

        return records, total
    except Exception as e:
        logger.exception(f"Error fetching ask history: {e}")
        return [], 0


# =========================
# MAIN ASK ENDPOINT
# =========================
@router.post("/", response_model=AskResponse, status_code=status.HTTP_200_OK)
def ask_ai(request: AskRequest, current_user: dict = Depends(get_current_user)):
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
    logger.info(
        f"Ask request: user_id={request.user_id}, question='{request.question[:50]}...'"
    )

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
                detail="Cannot ask questions for another user",
            )

        # 2️⃣ VALIDATE INPUTS
        if not request.question or len(request.question.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question must be at least 5 characters",
            )

        if len(request.question) > 2000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question cannot exceed 2000 characters",
            )

        if not request.goal or len(request.goal.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal must be at least 3 characters",
            )

        if not isinstance(request.level, LevelEnum):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid level"
            )

        logger.debug(f"Request validation passed: user={request.user_id}")

        # 3️⃣ CALL AI TUTOR SERVICE (orchestration)
        response = ai_tutor.ask_ai(
            user_id=request.user_id,
            question=request.question,
            goal=request.goal,
            level=_scalar_request_value(request.level),
            subject_id=_scalar_request_value(request.subject_id),
            completed=request.completed or [],
        )

        answer_payload = response.get("answer", {}) or {}
        concept_detected = response.get("concept_detected") or {}
        latency_ms = int(answer_payload.get("latency_ms", 0) or 0)
        llm_model = str(
            answer_payload.get("model") or response.get("model") or "unknown"
        )

        logger.info(
            f"Ask completed successfully: user={request.user_id}, "
            f"concept={concept_detected.get('concept_name')}"
        )

        event_logging_service.log_event(
            "llm_called",
            user_id=request.user_id,
            llm_model=llm_model,
            latency_ms=latency_ms,
            success=bool(response.get("success", False)),
            metadata={"goal": request.goal[:100], "level": _scalar_request_value(request.level)},
        )
        event_logging_service.log_event(
            "ai_response_generated",
            user_id=request.user_id,
            concept_id=concept_detected.get("concept_id"),
            success=bool(response.get("success", False)),
            latency_ms=latency_ms,
            metadata={
                "question_length": len(request.question or ""),
                "sources": len(answer_payload.get("sources", []) or []),
            },
        )

        detected_concept_id = concept_detected.get("concept_id")
        answer_confidence = float(
            response.get("answer", {}).get("confidence", 0.0) or 0.0
        )
        knowledge_tracing_service.update_from_interaction(
            user_id=request.user_id,
            event_type="ai_tutor_asked",
            concept_id=detected_concept_id,
            confidence=answer_confidence,
            metadata={"source": "ask_api", "goal": request.goal[:120]},
        )

        feedback_service.process_implicit_feedback(
            user_id=request.user_id,
            signal_type="ai_tutor_asked",
            concept_id=detected_concept_id,
            value=0.2,
            metadata={
                "goal": request.goal[:120],
                "question_length": len(request.question or ""),
                "answer_confidence": answer_confidence,
            },
        )

        # Save to ask history
        _save_ask_history(
            user_id=request.user_id,
            question=request.question,
            answer_text=response.get("answer", {}).get("answer_text", ""),
            goal=request.goal,
            level=_scalar_request_value(request.level),
            concept_id=detected_concept_id,
            concept_name=concept_detected.get("concept_name"),
            confidence=answer_confidence,
        )

        return AskResponse(
            success=response.get("success", False),
            answer=response.get("answer", {}),
            learning_path=response.get("learning_path", []),
            concept_detected=concept_detected or None,
            adaptive_info=response.get("adaptive_info"),
            progress_updated=response.get("progress_updated", False),
        )

    except HTTPException:
        raise
    except Exception as e:
        event_logging_service.log_event(
            "llm_failed",
            user_id=request.user_id,
            success=False,
            error_code=e.__class__.__name__,
            metadata={"goal": request.goal[:100], "level": _scalar_request_value(request.level)},
        )
        logger.exception(f"Ask error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Question processing failed",
        )


# =========================
# ADAPTIVE STATUS ENDPOINT
# =========================
@router.get(
    "/adaptive-status",
    response_model=AskAdaptiveStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_adaptive_status(
    user_id: str = Query(..., description="User ID (MongoDB ObjectId as string)"),
    concept_id: int = Query(..., ge=1, description="Concept ID"),
    current_user: dict = Depends(get_current_user),
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )

        # Get progress
        progress = get_progress(user_id=user_id, concept_id=concept_id)

        if not progress:
            logger.info(f"No progress found: user={user_id}, concept={concept_id}")
            return {
                "success": False,
                "message": "No progress data found",
                "user_id": user_id,
                "concept_id": concept_id,
            }

        # Generate adaptive summary
        summary = adaptive_decision_summary(
            mastery=float(progress.get("mastery", 0) or 0.0),
            confidence=float(progress.get("confidence", 0) or 0.0),
            total_attempts=int(progress.get("total_attempts", 0) or 0),
        )

        logger.info(
            f"Adaptive status: user={user_id}, concept={concept_id}, mode={summary['mode']}"
        )

        return {
            "success": True,
            "user_id": user_id,
            "concept_id": concept_id,
            "progress": progress,
            "adaptive_summary": summary,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting adaptive status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get adaptive status",
        )


# =========================
# BATCH CONCEPT DETECTION
# =========================
@router.post(
    "/detect-concepts",
    response_model=AskDetectConceptsResponse,
    status_code=status.HTTP_200_OK,
)
def detect_concepts_batch(
    payload: AskDetectConceptsRequest | None = Body(default=None),
    questions: list[str] | None = Query(
        default=None,
        description="List of question strings. Legacy query-string fallback.",
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Batch concept detection: map multiple questions to concepts.

    Args:
        questions: List of questions
        current_user: Current authenticated user

    Returns:
        List of detected concepts
    """
    effective_questions = (
        list(payload.questions)
        if payload and payload.questions
        else [str(item) for item in (questions or []) if str(item).strip()]
    )
    if not effective_questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="questions is required",
        )

    logger.info(f"Batch concept detection: {len(effective_questions)} questions")

    try:
        results = ai_tutor.detect_concepts_batch(effective_questions)
        normalized_results = [item or {} for item in results]
        return {
            "success": True,
            "total": len(effective_questions),
            "detected": normalized_results,
        }
    except Exception as e:
        logger.exception(f"Batch concept detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Concept detection failed",
        )


# =========================
# RECOMMEND CONCEPTS
# =========================
@router.get(
    "/recommend-concepts",
    response_model=AskRecommendedConceptsResponse,
    status_code=status.HTTP_200_OK,
)
def recommend_next_concepts(
    user_id: str = Query(..., description="User ID"),
    limit: int = Query(5, ge=1, le=20),
    goal: str | None = Query(None),
    level: str | None = Query(None),
    subject_id: str | None = Query(None),
    allow_generate: bool = Query(
        True,
        description="Allow creating a new learning path when no matching path exists",
    ),
    current_user: dict = Depends(get_current_user),
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )

        recommended = learning_path_service.recommend_next_concepts(
            user_id=user_id,
            limit=limit,
            goal=goal,
            level=level,
            subject_id=subject_id,
            allow_generate=allow_generate,
        )

        logger.info(f"Recommended {len(recommended)} concepts for user {user_id}")

        return {"success": True, "user_id": user_id, "recommended": recommended}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error recommending concepts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recommend concepts",
        )


# =========================
# 6. ASK HISTORY
# =========================
@router.get(
    "/history",
    response_model=AskHistoryResponse,
    status_code=status.HTTP_200_OK,
)
def get_ask_history(
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    goal: str = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Get user's question asking history.

    Parameters
    ----------
    limit : int
        Max records to return (1-100, default 50)
    skip : int
        Pagination offset (default 0)
    goal : str
        Optional filter by learning goal
    current_user : dict
        Current authenticated user

    Returns
    -------
    {
        "success": bool,
        "history": [
            {
                "_id": string (MongoDB ObjectId),
                "question": string,
                "answer": string,
                "goal": string,
                "level": string,
                "concept_name": string (optional),
                "confidence": float,
                "timestamp": string (ISO format)
            },
            ...
        ],
        "total": int,
        "limit": int,
        "skip": int
    }
    """
    try:
        user_id = str(current_user.get("_id", ""))

        logger.info(f"Getting ask history: user={user_id}, limit={limit}, skip={skip}")

        history, total = _get_ask_history(
            user_id=user_id, limit=limit, skip=skip, goal=goal
        )

        logger.info(f"Retrieved {len(history)} history records for user {user_id}")

        return {
            "success": True,
            "history": history,
            "total": total,
            "limit": limit,
            "skip": skip,
        }

    except Exception as e:
        logger.exception(f"Error getting ask history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve ask history",
        )


@router.delete(
    "/history/{history_id}",
    response_model=BasicMessageResponse,
    status_code=status.HTTP_200_OK,
)
def delete_ask_history_item(
    history_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Delete a specific question from ask history.

    Parameters
    ----------
    history_id : str
        MongoDB ObjectId of history item
    current_user : dict
        Current authenticated user

    Returns
    -------
    {
        "success": bool,
        "message": string
    }
    """
    try:
        from bson.objectid import ObjectId

        user_id = str(current_user.get("_id", ""))

        logger.info(f"Deleting ask history item: user={user_id}, item_id={history_id}")

        if not ObjectId.is_valid(history_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid history item id",
            )

        db = get_db()
        result = db.ask_history.delete_one(
            {"_id": ObjectId(history_id), "user_id": user_id}
        )

        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="History item not found"
            )

        logger.info(f"Deleted ask history item: {history_id}")

        return {"success": True, "message": "History item deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting ask history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete history item",
        )

