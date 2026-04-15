"""
Progress API: Update and track learner progress on concepts.
"""

from datetime import datetime, timedelta, timezone
import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    ConceptProgressResponse,
    ProgressUpdate,
    ProgressOverviewResponse,
    ProgressSummaryResponse,
    ProgressUpdateResponse,
    UserConfidenceOverviewResponse,
)
from backend.app.database.mongo import get_db
from backend.app.services.progress_tracking.progress import (
    get_progress,
    get_user_progress_summary,
    update_progress_with_confidence,
)
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.feedback_service import feedback_service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/progress", tags=["Progress"])


def _resolve_user_level(db, user_id: str) -> str:
    user = None
    try:
        if ObjectId.is_valid(user_id):
            user = db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        user = db.users.find_one({"_id": user_id})

    return user.get("level", "beginner") if user else "beginner"


def _average_progress_confidence(
    db, user_id: str, start: datetime, end: datetime = None
) -> tuple[float, int]:
    query = {
        "user_id": user_id,
        "last_updated": {"$gte": start},
    }
    if end is not None:
        query["last_updated"]["$lt"] = end

    cursor = db.progress.find(query, {"confidence": 1})
    total = 0.0
    count = 0
    for item in cursor:
        try:
            value = float(item.get("confidence", 0.0) or 0.0)
            total += max(0.0, min(1.0, value))
            count += 1
        except Exception:
            continue

    if count == 0:
        return 0.0, 0
    return total / count, count


@router.post(
    "/update", response_model=ProgressUpdateResponse, status_code=status.HTTP_200_OK
)
def update_progress_api(
    payload: ProgressUpdate, current_user: dict = Depends(get_current_user)
):
    logger.info(
        "Progress update request: user=%s, concept=%s, mastery=%s, confidence=%s",
        payload.user_id,
        payload.concept_id,
        payload.mastery,
        payload.confidence,
    )

    try:
        current_user_id = str(current_user.get("_id", ""))
        if current_user_id != payload.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update progress for another user",
            )

        if payload.mastery < 0 or payload.mastery > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mastery must be between 0 and 1",
            )

        if payload.confidence < 0 or payload.confidence > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Confidence must be between 0 and 1",
            )

        if payload.concept_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Concept ID must be positive",
            )

        previous = get_progress(payload.user_id, payload.concept_id) or {}
        prev_mastery = float(previous.get("mastery", 0.0) or 0.0)
        prev_confidence = float(previous.get("confidence", 0.0) or 0.0)

        result = update_progress_with_confidence(
            user_id=payload.user_id,
            concept_id=payload.concept_id,
            confidence=payload.confidence,
        )

        event_logging_service.log_event(
            "mastery_updated",
            user_id=payload.user_id,
            concept_id=payload.concept_id,
            mastery_before=prev_mastery,
            mastery_after=float(result.get("mastery", 0.0) or 0.0),
            success=True,
        )
        event_logging_service.log_event(
            "confidence_updated",
            user_id=payload.user_id,
            concept_id=payload.concept_id,
            confidence_before=prev_confidence,
            confidence_after=float(result.get("confidence", 0.0) or 0.0),
            success=True,
        )

        mastery_after = float(result.get("mastery", 0.0) or 0.0)
        confidence_after = float(result.get("confidence", 0.0) or 0.0)
        knowledge_tracing_service.update_from_interaction(
            user_id=payload.user_id,
            event_type="progress_updated",
            concept_id=payload.concept_id,
            confidence=confidence_after,
            is_correct=(confidence_after >= 0.6),
            metadata={"source": "progress_api", "mastery": mastery_after},
        )
        feedback_service.process_outcome_feedback(
            user_id=payload.user_id,
            concept_id=payload.concept_id,
            mastery_gain=(mastery_after - prev_mastery),
            confidence_gain=(confidence_after - prev_confidence),
            metadata={"source": "progress_api"},
        )

        return ProgressUpdateResponse(
            user_id=result.get("user_id"),
            concept_id=result.get("concept_id"),
            mastery=result.get("mastery"),
            confidence=result.get("confidence"),
            total_attempts=result.get("total_attempts", 1),
            status=result.get("status", "in_progress"),
            updated_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating progress: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update progress",
        ) from exc


@router.get(
    "/summary",
    response_model=ProgressSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_progress_summary(
    user_id: str = None, current_user: dict = Depends(get_current_user)
):
    if user_id is None:
        user_id = str(current_user.get("_id", ""))

    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's progress",
        )

    try:
        summary = get_user_progress_summary(user_id=user_id)
        return {
            "success": True,
            "user_id": user_id,
            "summary": summary,
        }

    except Exception as exc:
        logger.exception("Error getting progress summary: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch progress summary",
        ) from exc


@router.get(
    "/overview",
    response_model=ProgressOverviewResponse,
    status_code=status.HTTP_200_OK,
)
def get_progress_overview(
    user_id: str = None, current_user: dict = Depends(get_current_user)
):
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's progress overview",
        )

    try:
        summary = get_user_progress_summary(user_id=user_id)
        total = summary.get("total_concepts_started", 0)
        completed = summary.get("total_concepts_completed", 0)
        overall_progress_percent = (
            round((completed / total) * 100, 1) if total > 0 else 0.0
        )

        db = get_db()
        now = datetime.now(timezone.utc)
        week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=7
        )
        two_weeks_ago = week_ago - timedelta(days=7)

        recent_completed = db.progress.count_documents(
            {
                "user_id": user_id,
                "mastery": {"$gte": 0.8},
                "last_updated": {"$gte": week_ago},
            }
        )
        prev_week_completed = db.progress.count_documents(
            {
                "user_id": user_id,
                "mastery": {"$gte": 0.8},
                "last_updated": {"$gte": two_weeks_ago, "$lt": week_ago},
            }
        )

        weekly_comparison = 0.0
        if prev_week_completed > 0:
            weekly_comparison = round(
                ((recent_completed - prev_week_completed) / prev_week_completed) * 100,
                1,
            )
        elif recent_completed > 0:
            weekly_comparison = 100.0

        return {
            "success": True,
            "user_id": user_id,
            "overall_progress_percent": overall_progress_percent,
            "progress_bar": overall_progress_percent,
            "weekly_comparison_percent": weekly_comparison,
            "summary": summary,
        }

    except Exception as exc:
        logger.exception("Error getting progress overview: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch progress overview",
        ) from exc


@router.get(
    "/confidence",
    response_model=UserConfidenceOverviewResponse,
    status_code=status.HTTP_200_OK,
)
def get_progress_confidence(
    user_id: str = None, current_user: dict = Depends(get_current_user)
):
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's confidence overview",
        )

    try:
        summary = get_user_progress_summary(user_id=user_id)
        base_confidence = float(summary.get("average_confidence", 0.0) or 0.0)
        base_confidence = max(0.0, min(1.0, base_confidence))

        db = get_db()
        level = _resolve_user_level(db, user_id)

        now = datetime.now(timezone.utc)
        week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=7
        )
        two_weeks_ago = week_ago - timedelta(days=7)

        recent_avg, recent_count = _average_progress_confidence(db, user_id, week_ago)
        prev_avg, prev_count = _average_progress_confidence(
            db, user_id, two_weeks_ago, week_ago
        )

        if recent_count == 0:
            recent_avg = base_confidence
        if prev_count == 0:
            prev_avg = base_confidence

        if recent_avg > prev_avg + 0.02:
            trend = "↑ improving"
        elif recent_avg < prev_avg - 0.02:
            trend = "↓ declining"
        else:
            trend = "→ stable"

        return {
            "success": True,
            "user_id": user_id,
            "confidence": round(base_confidence, 2),
            "level": level,
            "trend": trend,
            "explanation": "Confidence duoc tong hop tu tien do hoc tap theo concept.",
            "details": {
                "base_confidence": round(base_confidence, 3),
                "recent_event_count": recent_count,
                "previous_event_count": prev_count,
                "recent_period_confidence": round(recent_avg, 3),
                "previous_period_confidence": round(prev_avg, 3),
            },
        }

    except Exception as exc:
        logger.exception("Error getting confidence overview: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch confidence overview",
        ) from exc


@router.get(
    "/concept/{concept_id}",
    response_model=ConceptProgressResponse,
    status_code=status.HTTP_200_OK,
)
def get_concept_progress_api(
    concept_id: int, user_id: str = None, current_user: dict = Depends(get_current_user)
):
    if user_id is None:
        user_id = str(current_user.get("_id", ""))

    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's concept progress",
        )

    try:
        progress = get_progress(user_id=user_id, concept_id=concept_id)
        return {
            "success": True,
            "user_id": user_id,
            "concept_id": concept_id,
            "progress": progress,
        }
    except Exception as exc:
        logger.exception("Error getting concept progress: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch concept progress",
        ) from exc
