"""
Progress API: Update and track learner progress on concepts.

Endpoints:
- POST /progress/update: Update progress on a concept (mastery + confidence)
- GET /progress/summary: Get user's progress summary across all concepts
- GET /progress/concept/{concept_id}: Get concept progress analytics
- GET /progress/overview: Get overall progress overview (%, progress bar, weekly comparison)
- GET /progress/confidence: Get user confidence overview with trend

Features:
- EMA-based progress tracking (exponential moving average)
- Confidence-based mastery updates
- Status tracking (not_started → in_progress → proficient → complete)
- Success rate calculation
- Comprehensive logging + error handling

All endpoints include:
- Authentication (requires JWT token)
- Authorization (must be updating own progress)
- Input validation
- Error handling with specific HTTP codes
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
from bson import ObjectId

from backend.app.services.progress_service import (
    update_progress_with_confidence,
    get_user_progress_summary,
    get_progress
)
from backend.app.api.auth import get_current_user
from backend.app.api.schemas import ProgressUpdate, ProgressUpdateResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/progress", tags=["Progress"])


def _resolve_user_level(db, user_id: str) -> str:
    """Resolve user level with ObjectId-safe lookup."""
    user = None
    try:
        if ObjectId.is_valid(user_id):
            user = db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        user = db.users.find_one({"_id": user_id})

    return user.get("level", "beginner") if user else "beginner"


def _get_assessment_confidence(db, user_id: str) -> tuple[float, int]:
    """
    Aggregate lesson assessment score_percent into [0,1] confidence signal.
    Returns (confidence, counted_lessons).
    """
    paths = list(db.learning_paths.find({"user_id": user_id}, {"curriculum": 1}))
    if not paths:
        return 0.0, 0

    total = 0.0
    count = 0
    for path in paths:
        for chapter in path.get("curriculum", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                assessment = lesson.get("assessment") or {}
                if "score_percent" not in assessment:
                    continue
                try:
                    score_percent = float(assessment.get("score_percent", 0.0) or 0.0)
                    score_percent = max(0.0, min(100.0, score_percent))
                    total += score_percent / 100.0
                    count += 1
                except Exception:
                    continue

    if count == 0:
        return 0.0, 0
    return total / count, count


def _average_confidence_events(db, user_id: str, start: datetime, end: datetime = None) -> tuple[float, int]:
    query = {
        "user_id": user_id,
        "created_at": {"$gte": start}
    }
    if end is not None:
        query["created_at"]["$lt"] = end

    cursor = db.confidence_events.find(query, {"confidence": 1})
    total = 0.0
    count = 0
    for item in cursor:
        try:
            value = float(item.get("confidence", 0.0) or 0.0)
            value = max(0.0, min(1.0, value))
            total += value
            count += 1
        except Exception:
            continue

    if count == 0:
        return 0.0, 0
    return total / count, count


# =========================
# API
# =========================
@router.post("/update", response_model=ProgressUpdateResponse, status_code=status.HTTP_200_OK)
def update_progress_api(
    payload: ProgressUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update learning progress on a concept.
    
    Pipeline:
    1. Validate user authorization (current_user._id == payload.user_id)
    2. Validate input fields (mastery/confidence [0,1], concept_id > 0)
    3. Call ProgressService.update_progress_with_confidence()
       - EMA update formula: new_mastery = old * (1-α) + confidence * α
       - Update status field (not_started → in_progress → proficient → complete)
       - Increment total_attempts, successful_attempts
       - Calculate success_rate
    4. Return updated progress
    
    Args:
        payload: ProgressUpdate with user_id, concept_id, mastery, confidence, total_attempts
        current_user: Current authenticated user (from JWT token)
        
    Returns:
        ProgressUpdateResponse with user_id, concept_id, mastery, confidence, 
        total_attempts, status, updated_at
        
    Raises:
        HTTPException(401): If user_id doesn't match current_user
        HTTPException(400): If validation fails (mastery/confidence not [0,1], etc.)
        HTTPException(500): If database error
        
    Example:
        >>> {
        ...     "user_id": "507f1f77bcf86cd799439011",
        ...     "concept_id": 5,
        ...     "mastery": 0.75,
        ...     "confidence": 0.85,
        ...     "total_attempts": 3
        ... }
    """
    logger.info(
        f"Progress update request: user={payload.user_id}, concept={payload.concept_id}, "
        f"mastery={payload.mastery}, confidence={payload.confidence}"
    )
    
    try:
        # 1️⃣ VALIDATE AUTHORIZATION
        current_user_id = str(current_user.get("_id", ""))
        
        if current_user_id != payload.user_id:
            logger.warning(
                f"Unauthorized progress update: auth_user={current_user_id}, "
                f"request_user={payload.user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update progress for another user"
            )
        
        # 2️⃣ VALIDATE INPUTS
        if payload.mastery < 0 or payload.mastery > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mastery must be between 0 and 1"
            )
        
        if payload.confidence < 0 or payload.confidence > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Confidence must be between 0 and 1"
            )
        
        if payload.concept_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Concept ID must be positive"
            )
        
        logger.debug(f"Progress update validation passed")
        
        # 3️⃣ UPDATE PROGRESS
        result = update_progress_with_confidence(
            user_id=payload.user_id,
            concept_id=payload.concept_id,
            confidence=payload.confidence
        )
        
        logger.info(
            f"Progress updated: user={payload.user_id}, concept={payload.concept_id}, "
            f"new_mastery={result.get('mastery')}, status={result.get('status')}"
        )
        
        return ProgressUpdateResponse(
            user_id=result.get("user_id"),
            concept_id=result.get("concept_id"),
            mastery=result.get("mastery"),
            confidence=result.get("confidence"),
            total_attempts=result.get("total_attempts", 1),
            status=result.get("status", "in_progress"),
            updated_at=datetime.utcnow()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update progress"
        )


@router.get("/summary", status_code=status.HTTP_200_OK)
def get_progress_summary(
    user_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's progress summary across all concepts.
    
    Args:
        user_id: Optional user ID (if not provided, uses current_user)
        current_user: Current authenticated user
        
    Returns:
        Dict with:
        - user_id: str
        - total_concepts_started: int
        - total_concepts_completed: int
        - average_mastery: float
        - average_confidence: float
        - concepts: List[Dict] (detailed per-concept progress)
    """
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    
    # Authorization
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's progress"
        )
    
    logger.info(f"Progress summary requested: user={user_id}")
    
    try:
        summary = get_user_progress_summary(user_id=user_id)
        
        logger.info(
            f"Progress summary: user={user_id}, "
            f"started={summary.get('total_concepts_started')}, "
            f"completed={summary.get('total_concepts_completed')}"
        )
        
        return {
            "success": True,
            "user_id": user_id,
            "summary": summary
        }
    
    except Exception as e:
        logger.exception(f"Error getting progress summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch progress summary"
        )



# =========================
# OVERALL PROGRESS OVERVIEW
# =========================
@router.get("/overview", status_code=status.HTTP_200_OK)
def get_progress_overview(
    user_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get overall progress overview for the user.
    Returns:
        - overall_progress_percent: float
        - progress_bar: float (same as percent)
        - weekly_comparison: float (percent change vs last week)
        - summary: dict (detailed progress summary)
    """
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's progress overview"
        )
    logger.info(f"Progress overview requested: user={user_id}")
    try:
        from backend.app.services.progress_service import get_user_progress_summary
        from backend.app.services.progress_service import get_db
        summary = get_user_progress_summary(user_id=user_id)
        # Overall progress: % completed concepts / total concepts
        total = summary.get("total_concepts_started", 0)
        completed = summary.get("total_concepts_completed", 0)
        overall_progress_percent = round((completed / total) * 100, 1) if total > 0 else 0.0
        progress_bar = overall_progress_percent
        # Weekly comparison: compare completed concepts this week vs last week
        db = get_db()
        now = datetime.utcnow()
        week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        # Find progress completed in last week
        recent_completed = db.progress.count_documents({
            "user_id": user_id,
            "mastery": {"$gte": 0.8},
            "last_updated": {"$gte": week_ago}
        })
        # Find progress completed in week before last week
        two_weeks_ago = week_ago - timedelta(days=7)
        prev_week_completed = db.progress.count_documents({
            "user_id": user_id,
            "mastery": {"$gte": 0.8},
            "last_updated": {"$gte": two_weeks_ago, "$lt": week_ago}
        })
        # Calculate percent change
        weekly_comparison = 0.0
        if prev_week_completed > 0:
            weekly_comparison = round(((recent_completed - prev_week_completed) / prev_week_completed) * 100, 1)
        elif recent_completed > 0:
            weekly_comparison = 100.0
        # Response
        return {
            "success": True,
            "user_id": user_id,
            "overall_progress_percent": overall_progress_percent,
            "progress_bar": progress_bar,
            "weekly_comparison_percent": weekly_comparison,
            "summary": summary
        }
    except Exception as e:
        logger.exception(f"Error getting progress overview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch progress overview"
        )


# =========================
# USER CONFIDENCE OVERVIEW
# =========================
@router.get("/confidence", status_code=status.HTTP_200_OK)
def get_progress_confidence(
    user_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's confidence overview.
    Returns:
        - confidence: float (average confidence)
        - level: str (current user level)
        - trend: str (improving, declining, stable)
        - explanation: str (how confidence is evaluated)
    """
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's confidence overview"
        )
    logger.info(f"Confidence overview requested: user={user_id}")
    try:
        from backend.app.services.progress_service import get_user_progress_summary, get_db
        summary = get_user_progress_summary(user_id=user_id)

        # Base confidence from concept progress
        base_confidence = float(summary.get("average_confidence", 0.0) or 0.0)
        base_confidence = max(0.0, min(1.0, base_confidence))

        # Get DB handle
        db = get_db()

        # Resolve user level robustly (ObjectId/string)
        level = _resolve_user_level(db, user_id)

        # Assessment-based confidence from lesson quizzes
        assessment_confidence, assessed_lessons = _get_assessment_confidence(db, user_id)

        # Blend signals: concept confidence + lesson assessment confidence
        if assessed_lessons > 0:
            confidence = (base_confidence * 0.7) + (assessment_confidence * 0.3)
        else:
            confidence = base_confidence
        confidence = max(0.0, min(1.0, confidence))

        # Trend: compare average confidence this week vs last week
        now = datetime.utcnow()
        week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        two_weeks_ago = week_ago - timedelta(days=7)

        # Prefer event-based trend (time-series from lesson submissions)
        recent_avg, recent_count = _average_confidence_events(db, user_id, week_ago)
        prev_avg, prev_count = _average_confidence_events(db, user_id, two_weeks_ago, week_ago)

        # Fallback to progress snapshots if event stream is insufficient
        if recent_count == 0:
            recent_confidences = db.progress.find({
                "user_id": user_id,
                "last_updated": {"$gte": week_ago}
            })
            snapshot_total = 0.0
            snapshot_count = 0
            for p in recent_confidences:
                snapshot_total += float(p.get("confidence", 0.0) or 0.0)
                snapshot_count += 1
            recent_avg = snapshot_total / snapshot_count if snapshot_count > 0 else confidence

        if prev_count == 0:
            prev_confidences = db.progress.find({
                "user_id": user_id,
                "last_updated": {"$gte": two_weeks_ago, "$lt": week_ago}
            })
            snapshot_total = 0.0
            snapshot_count = 0
            for p in prev_confidences:
                snapshot_total += float(p.get("confidence", 0.0) or 0.0)
                snapshot_count += 1
            prev_avg = snapshot_total / snapshot_count if snapshot_count > 0 else base_confidence

        # Determine trend
        if recent_avg > prev_avg + 0.02:
            trend = "↑ improving"
        elif recent_avg < prev_avg - 0.02:
            trend = "↓ declining"
        else:
            trend = "→ stable"

        explanation = (
            "Hệ thống đánh giá mức độ tự tin dựa trên trung bình confidence theo concept "
            "và kết quả quiz trong learning path (nếu có)."
        )

        return {
            "success": True,
            "user_id": user_id,
            "confidence": round(confidence, 2),
            "level": level,
            "trend": trend,
            "explanation": explanation,
            "details": {
                "base_confidence": round(base_confidence, 3),
                "assessment_confidence": round(assessment_confidence, 3),
                "assessed_lessons": assessed_lessons,
                "recent_event_count": recent_count,
                "previous_event_count": prev_count,
                "recent_period_confidence": round(recent_avg, 3),
                "previous_period_confidence": round(prev_avg, 3)
            }
        }
    except Exception as e:
        logger.exception(f"Error getting confidence overview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch confidence overview"
        )