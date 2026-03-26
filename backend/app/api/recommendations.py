from fastapi import APIRouter, Query, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
import logging

from backend.app.api.schemas import LevelEnum
from backend.app.api.auth import get_current_user
from backend.app.database.mongo import db
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.hybrid_recommendation_service import (
    hybrid_recommendation_service,
)
from backend.app.services.feedback_service import feedback_service
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# =========================
# SCHEMAS
# =========================
class ResourceItem(BaseModel):
    resource_id: int
    title: str
    source: str
    level: str
    topic: str
    url: Optional[str] = None
    reason: str
    relevance_score: float = Field(ge=0, le=1)
    score_breakdown: Optional[dict] = None
    rank_position: Optional[int] = None


class PersonalizedRecommendationResponse(BaseModel):
    user_id: str
    goal: str
    level: str
    recommended_resources: List[ResourceItem]
    completed_concepts: int
    total_concepts: int
    progress_percentage: float
    message: str
    reranking_metadata: Optional[dict] = None


class ConceptProgressItem(BaseModel):
    concept_id: int
    concept_name: str
    difficulty: int
    mastery: float
    status: str  # "completed", "in-progress", "not-started"


class LearningProgressResponse(BaseModel):
    user_id: str
    goal: str
    concepts: List[ConceptProgressItem]
    overall_mastery: float
    message: str


class RecommendationInteractionRequest(BaseModel):
    recommendation_id: Optional[str] = None
    resource_id: Optional[int] = None
    concept_id: Optional[int] = None
    lesson_id: Optional[str] = None
    goal: Optional[str] = None
    level: Optional[str] = None
    metadata: Optional[dict] = None


class RecommendationFeedbackRequest(BaseModel):
    recommendation_id: Optional[str] = None
    resource_id: Optional[int] = None
    lesson_id: Optional[str] = None
    concept_id: Optional[int] = None
    feedback_type: Literal["helpful", "not_helpful", "save_for_later", "hide"]
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[dict] = None


# =========================
# HELPER
# =========================
def enum_to_string(value) -> str:
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _resolve_requested_user_id(
    requested_user_id: str | None, current_user: dict
) -> str:
    auth_object_id = str(current_user.get("_id", ""))
    auth_numeric_id = current_user.get("user_id")
    auth_numeric_id_str = str(auth_numeric_id) if auth_numeric_id is not None else None

    if requested_user_id is None or str(requested_user_id).strip() == "":
        return auth_numeric_id_str or auth_object_id

    requested_str = str(requested_user_id)
    if requested_str == auth_object_id:
        return requested_str
    if auth_numeric_id_str is not None and requested_str == auth_numeric_id_str:
        return requested_str

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# =========================
# GET PERSONALIZED RECOMMENDATIONS
# =========================
@router.get(
    "/resources",
    response_model=PersonalizedRecommendationResponse,
    summary="Get personalized learning resource recommendations",
)
def get_personalized_resources(
    user_id: Optional[str] = Query(
        None, description="User ID (ObjectId or numeric user_id)"
    ),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    level: LevelEnum = Query(LevelEnum.beginner, description="Current level"),
    limit: int = Query(10, ge=1, le=50, description="Max recommendations"),
    include_breakdown: bool = Query(True, description="Include hybrid score breakdown"),
    enable_reranking: bool = Query(
        True, description="Enable diversity-aware reranking"
    ),
    current_user=Depends(get_current_user),
):
    """
    Get personalized learning resource recommendations based on:
    - Learning goal & topic
    - Current level
    - Completed concepts (progress)
    - Resource relevance & type

    Requires: authenticated user (can only get own recommendations)
    """
    effective_user_id = _resolve_requested_user_id(user_id, current_user)

    try:
        level_str = enum_to_string(level)
        result = hybrid_recommendation_service.recommend_resources(
            user_id=effective_user_id,
            goal=goal,
            level=level_str,
            limit=limit,
            enable_reranking=enable_reranking,
        )

        recommended = result.get("recommended", [])
        if not include_breakdown:
            for item in recommended:
                item.pop("score_breakdown", None)

        progress_pct = float(result.get("progress_percentage", 0.0) or 0.0)

        logger.info(
            f"Personalized recommendations: user={user_id}, goal={goal}, "
            f"level={level_str}, resources={len(recommended)}"
        )
        event_logging_service.log_event(
            "recommendation_shown",
            user_id=effective_user_id,
            success=True,
            metadata={
                "goal": goal,
                "level": level_str,
                "count": len(recommended),
                "reranking": result.get("reranking", {}).get("strategy"),
                "diversity_ratio": result.get("reranking", {}).get("diversity_ratio"),
            },
        )

        for idx, item in enumerate(recommended, start=1):
            event_logging_service.log_event(
                "recommendation_shown",
                user_id=effective_user_id,
                resource_id=item.get("resource_id"),
                rank_position=idx,
                recommendation_score=item.get("relevance_score"),
                success=True,
                metadata={"goal": goal, "level": level_str},
            )

        return {
            "user_id": effective_user_id,
            "goal": goal,
            "level": level_str,
            "recommended_resources": recommended,
            "completed_concepts": int(result.get("completed_concepts", 0)),
            "total_concepts": int(result.get("total_concepts", 0)),
            "progress_percentage": round(progress_pct, 1),
            "message": f"Found {len(recommended)} hybrid recommendations. Progress: {progress_pct:.1f}%",
            "reranking_metadata": result.get("reranking", {}),
        }

    except Exception as e:
        event_logging_service.log_event(
            "recommendation_shown",
            user_id=effective_user_id,
            success=False,
            error_code=e.__class__.__name__,
            metadata={"goal": goal, "level": enum_to_string(level)},
        )
        logger.exception(
            f"Error generating recommendations for user {effective_user_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate recommendations",
        )


@router.get("/resources/debug", summary="Debug hybrid recommendation signals")
def debug_personalized_resources(
    user_id: Optional[str] = Query(
        None, description="User ID (ObjectId or numeric user_id)"
    ),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    level: LevelEnum = Query(LevelEnum.beginner, description="Current level"),
    limit: int = Query(10, ge=1, le=50, description="Max recommendations"),
    enable_reranking: bool = Query(
        True, description="Enable diversity-aware reranking"
    ),
    current_user=Depends(get_current_user),
):
    """Return debug snapshot for recommendation tuning and troubleshooting."""
    effective_user_id = _resolve_requested_user_id(user_id, current_user)

    try:
        level_str = enum_to_string(level)
        debug_payload = hybrid_recommendation_service.recommendation_debug_snapshot(
            user_id=effective_user_id,
            goal=goal,
            level=level_str,
            limit=limit,
            enable_reranking=enable_reranking,
        )
        event_logging_service.log_event(
            "recommendation_debug_viewed",
            user_id=effective_user_id,
            success=True,
            metadata={"goal": goal, "level": level_str, "limit": limit},
        )
        return debug_payload
    except Exception as exc:
        logger.exception("Error generating recommendation debug snapshot: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate recommendation debug snapshot",
        ) from exc


# =========================
# GET LEARNING PROGRESS FOR GOAL
# =========================
@router.get(
    "/progress",
    response_model=LearningProgressResponse,
    summary="Get learning progress for a specific goal",
)
def get_learning_progress(
    user_id: Optional[str] = Query(
        None, description="User ID (ObjectId or numeric user_id)"
    ),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    current_user=Depends(get_current_user),
):
    """
    Get detailed progress on all concepts for a learning goal.

    Returns:
    - List of concepts with mastery level
    - Overall mastery percentage
    - Status of each concept (not-started, in-progress, completed)

    Requires: authenticated user
    """
    effective_user_id = _resolve_requested_user_id(user_id, current_user)

    try:
        # Get concepts for goal
        concepts = list(
            db.concepts.find(
                {"topic": {"$regex": goal, "$options": "i"}},
                {"concept_id": 1, "concept_name": 1, "difficulty": 1},
            ).sort("difficulty", 1)
        )

        if not concepts:
            return {
                "user_id": effective_user_id,
                "goal": goal,
                "concepts": [],
                "overall_mastery": 0,
                "message": f"No concepts found for goal: {goal}",
            }

        concept_ids = [c["concept_id"] for c in concepts]

        # Get user progress
        progress = list(
            db.progress.find(
                {"user_id": effective_user_id, "concept_id": {"$in": concept_ids}}
            )
        )
        mastery_map = {p["concept_id"]: p.get("mastery", 0) for p in progress}

        # Build concept progress list
        concept_progress = []
        total_mastery = 0

        for concept in concepts:
            cid = concept["concept_id"]
            mastery = mastery_map.get(cid, 0)

            # Determine status
            if mastery >= 0.8:
                status = "completed"
            elif mastery > 0:
                status = "in-progress"
            else:
                status = "not-started"

            concept_progress.append(
                {
                    "concept_id": cid,
                    "concept_name": concept.get("concept_name"),
                    "difficulty": concept.get("difficulty", 0),
                    "mastery": round(mastery, 2),
                    "status": status,
                }
            )

            total_mastery += mastery

        overall = (total_mastery / len(concepts) * 100) if concepts else 0

        logger.info(
            f"Progress retrieved: user={effective_user_id}, goal={goal}, overall={overall:.1f}%"
        )

        return {
            "user_id": effective_user_id,
            "goal": goal,
            "concepts": concept_progress,
            "overall_mastery": round(overall, 1),
            "message": f"Overall mastery for {goal}: {overall:.1f}%",
        }

    except Exception as e:
        logger.exception(f"Error getting progress for user {effective_user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve progress",
        )


@router.post("/events/click", summary="Track recommendation/resource click")
def track_recommendation_click(
    payload: RecommendationInteractionRequest,
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id", ""))
    event_logging_service.log_event(
        "recommendation_clicked",
        user_id=user_id,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        success=True,
        metadata={
            "recommendation_id": payload.recommendation_id,
            "goal": payload.goal,
            "level": payload.level,
            **(payload.metadata or {}),
        },
    )
    if payload.resource_id is not None:
        event_logging_service.log_event(
            "resource_clicked",
            user_id=user_id,
            lesson_id=payload.lesson_id,
            concept_id=payload.concept_id,
            resource_id=payload.resource_id,
            success=True,
            metadata={
                "recommendation_id": payload.recommendation_id,
                "goal": payload.goal,
                "level": payload.level,
                **(payload.metadata or {}),
            },
        )
        feedback_service.process_implicit_feedback(
            user_id=user_id,
            signal_type="resource_clicked",
            lesson_id=payload.lesson_id,
            concept_id=payload.concept_id,
            resource_id=payload.resource_id,
            value=0.35,
            metadata={
                "goal": payload.goal,
                "level": payload.level,
                **(payload.metadata or {}),
            },
        )
        knowledge_tracing_service.update_from_interaction(
            user_id=user_id,
            event_type="resource_clicked",
            lesson_id=payload.lesson_id,
            concept_id=payload.concept_id,
            metadata={"source": "recommendation_click"},
        )
    return {"ok": True}


@router.post("/events/resource-completed", summary="Track resource completion")
def track_resource_completed(
    payload: RecommendationInteractionRequest,
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id", ""))
    event_logging_service.log_event(
        "resource_completed",
        user_id=user_id,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        success=True,
        metadata={
            "recommendation_id": payload.recommendation_id,
            "goal": payload.goal,
            "level": payload.level,
            **(payload.metadata or {}),
        },
    )
    feedback_service.process_implicit_feedback(
        user_id=user_id,
        signal_type="resource_completed",
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        value=0.65,
        metadata={
            "goal": payload.goal,
            "level": payload.level,
            **(payload.metadata or {}),
        },
    )
    knowledge_tracing_service.update_from_interaction(
        user_id=user_id,
        event_type="resource_completed",
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        is_correct=True,
        metadata={"source": "resource_completed"},
    )
    return {"ok": True}


@router.post("/feedback", summary="Submit explicit recommendation feedback")
def submit_recommendation_feedback(
    payload: RecommendationFeedbackRequest,
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id", ""))

    event_logging_service.log_event(
        "recommendation_feedback",
        user_id=user_id,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        success=True,
        metadata={
            "recommendation_id": payload.recommendation_id,
            "feedback_type": payload.feedback_type,
            "rating": payload.rating,
            "comment": payload.comment,
            **(payload.metadata or {}),
        },
    )

    # Strong explicit positive/negative signals for CF pipeline.
    if payload.feedback_type == "helpful":
        event_logging_service.log_event(
            "recommendation_clicked",
            user_id=user_id,
            lesson_id=payload.lesson_id,
            concept_id=payload.concept_id,
            resource_id=payload.resource_id,
            success=True,
            metadata={
                "source": "explicit_feedback",
                "feedback_type": payload.feedback_type,
            },
        )
    elif payload.feedback_type == "hide":
        event_logging_service.log_event(
            "recommendation_hidden",
            user_id=user_id,
            lesson_id=payload.lesson_id,
            concept_id=payload.concept_id,
            resource_id=payload.resource_id,
            success=True,
            metadata={
                "source": "explicit_feedback",
                "feedback_type": payload.feedback_type,
            },
        )

    feedback_service.record_explicit_feedback(
        user_id=user_id,
        feedback_type=payload.feedback_type,
        value=payload.comment or payload.feedback_type,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        resource_id=payload.resource_id,
        metadata={
            "recommendation_id": payload.recommendation_id,
            "rating": payload.rating,
            **(payload.metadata or {}),
        },
    )

    kt_event = (
        "feedback_helpful"
        if payload.feedback_type in {"helpful", "save_for_later"}
        else "feedback_too_difficult"
    )
    knowledge_tracing_service.update_from_interaction(
        user_id=user_id,
        event_type=kt_event,
        lesson_id=payload.lesson_id,
        concept_id=payload.concept_id,
        metadata={
            "source": "recommendation_feedback",
            "feedback_type": payload.feedback_type,
        },
    )

    return {
        "ok": True,
        "message": "Feedback received",
        "feedback_type": payload.feedback_type,
    }
