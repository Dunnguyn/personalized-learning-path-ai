"""
Learning Path API: Generate personalized learning paths for users.

Endpoints:
- POST /learning-path/generate: Generate adaptive learning path for user

Features:
- Goal-based path generation
- Level-aware difficulty selection
- Prerequisite-aware ordering
- Adaptive mode integration (remedial/normal/advanced)
- Resource recommendations per concept
- Cycle detection + topological sorting

All endpoints include:
- Authentication (requires JWT token)
- Authorization (updating own path only)
- Input validation
- Error handling with specific HTTP codes
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import logging

from backend.app.services.learning_path_service import generate_learning_path
from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    LevelEnum,
    LearningPathResponse,
    LearningPathItemResponse,
    LessonProgressUpdate,
    LessonProgressResponse
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


def _build_lesson_progress(curriculum: Optional[List[dict]]) -> dict:
    progress = {}
    for chapter in curriculum or []:
        for lesson in chapter.get("lessons", []):
            lesson_id = lesson.get("lesson_id")
            if lesson_id and lesson_id not in progress:
                progress[lesson_id] = "not_started"
    return progress


def _apply_lesson_progress(curriculum: Optional[List[dict]], lesson_progress: dict) -> Optional[List[dict]]:
    if not curriculum:
        return curriculum

    for chapter in curriculum:
        for lesson in chapter.get("lessons", []):
            lesson_id = lesson.get("lesson_id")
            if lesson_id:
                lesson["status"] = lesson_progress.get(lesson_id, "not_started")
    return curriculum


# =========================
# REQUEST SCHEMA
# =========================
class LearningPathRequest(BaseModel):
    """Request to generate learning path."""
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    goal: str = Field(..., min_length=3, max_length=500, description="Learning goal")
    level: LevelEnum = Field(..., description="Learning level (beginner/intermediate/advanced)")


# =========================
# API
# =========================
@router.post("/generate", response_model=LearningPathResponse, status_code=status.HTTP_200_OK)
def generate_learning_path_api(
    payload: LearningPathRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate personalized learning path for user.
    
    Pipeline:
    1. Validate user authorization (current_user._id == payload.user_id)
    2. Validate inputs (goal length, level enum)
    3. Call LearningPathService.generate_learning_path()
       - Determine current proficiency (from progress)
       - Identify prerequisite graph (prerequisites → postrequisites)
       - Detect cycles in prerequisites
       - Topological sort for safe ordering
       - Filter resources by level
       - Integrate adaptive mode (remedial/normal/advanced)
       - Rank concepts by priority (difficulty + prerequisites + progress)
       - Select top-N concepts to recommend
    4. Return ordered path with resource recommendations
    
    Args:
        payload: LearningPathRequest with user_id, goal, level
        current_user: Current authenticated user (from JWT token)
        
    Returns:
        LearningPathResponse with:
        - path_id: UUID
        - user_id: str (MongoDB ObjectId)
        - goal: str
        - level: LevelEnum
        - generated_at: datetime
        - recommended_path: List[LearningPathItemResponse] (ordered concepts)
        - message: str (summary)
        
    Raises:
        HTTPException(401): If user_id doesn't match current_user
        HTTPException(400): If validation fails
        HTTPException(500): If internal error
        
    Example:
        >>> {
        ...     "user_id": "507f1f77bcf86cd799439011",
        ...     "goal": "Master Python fundamentals",
        ...     "level": "beginner"
        ... }
    """
    logger.info(
        f"Learning path generation requested: user={payload.user_id}, "
        f"goal='{payload.goal[:50]}...', level={payload.level}"
    )
    
    try:
        # 1️⃣ VALIDATE AUTHORIZATION
        current_user_id = str(current_user.get("_id", ""))
        
        if current_user_id != payload.user_id:
            logger.warning(
                f"Unauthorized learning path request: auth_user={current_user_id}, "
                f"request_user={payload.user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cannot generate learning path for another user"
            )
        
        # 2️⃣ VALIDATE INPUTS
        if not payload.goal or len(payload.goal.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal must be at least 3 characters"
            )
        
        if len(payload.goal) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal cannot exceed 500 characters"
            )
        
        if not isinstance(payload.level, LevelEnum):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid level"
            )
        
        logger.debug(f"Learning path request validation passed")
        
        # 3️⃣ GENERATE PATH
        result = generate_learning_path(
            user_id=payload.user_id,
            goal=payload.goal,
            level=payload.level.value if hasattr(payload.level, "value") else payload.level
        )

        curriculum = _apply_lesson_progress(
            result.get("curriculum"),
            _build_lesson_progress(result.get("curriculum"))
        )

        # 4️⃣ SAVE PATH HISTORY (best-effort)
        try:
            from backend.app.database.mongo import get_db
            db = get_db()
            lesson_progress = _build_lesson_progress(curriculum)
            db.learning_paths.insert_one({
                "path_id": result.get("path_id"),
                "user_id": payload.user_id,
                "goal": payload.goal,
                "level": payload.level.value if hasattr(payload.level, "value") else payload.level,
                "generated_at": datetime.utcnow(),
                "recommended_path": result.get("recommended_path", []),
                "curriculum": curriculum or [],
                "lesson_progress": lesson_progress,
                "message": result.get("message", "Learning path generated successfully")
            })
        except Exception as save_error:
            logger.warning(f"Failed to save learning path history: {save_error}")
        
        logger.info(
            f"Learning path generated: user={payload.user_id}, "
            f"path_id={result.get('path_id')}, concepts={len(result.get('recommended_path', []))}"
        )
        
        return LearningPathResponse(
            path_id=result.get("path_id"),
            user_id=payload.user_id,
            goal=payload.goal,
            level=payload.level,
            generated_at=datetime.utcnow(),
            recommended_path=result.get("recommended_path", []),
            curriculum=curriculum,
            message=result.get("message", "Learning path generated successfully")
        )
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"Error generating learning path: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate learning path"
        )


@router.get("/history", status_code=status.HTTP_200_OK)
def get_learning_path_history(
    user_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get history of generated learning paths for user.
    
    Args:
        user_id: Optional user ID (if not provided, uses current_user)
        current_user: Current authenticated user
        
    Returns:
        List of previously generated paths with timestamps
    """
    if user_id is None:
        user_id = str(current_user.get("_id", ""))
    
    # Authorization
    if str(current_user.get("_id")) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another user's path history"
        )
    
    logger.info(f"Learning path history requested: user={user_id}")
    
    try:
        from backend.app.database.mongo import get_db
        db = get_db()
        
        paths = list(
            db.learning_paths.find(
                {"user_id": user_id}
            ).sort("generated_at", -1).limit(10)
        )
        
        # Serialize ObjectIds
        for p in paths:
            if "_id" in p:
                p["_id"] = str(p["_id"])
        
        logger.info(f"Retrieved {len(paths)} learning paths for user {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "paths": paths
        }
    
    except Exception as e:
        logger.exception(f"Error fetching path history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch learning path history"
        )


@router.post("/lesson-progress", response_model=LessonProgressResponse, status_code=status.HTTP_200_OK)
def update_lesson_progress(
    payload: LessonProgressUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update lesson progress status for a learning path."""
    user_id = str(current_user.get("_id", ""))

    try:
        from backend.app.database.mongo import get_db
        db = get_db()

        path = db.learning_paths.find_one({
            "path_id": payload.path_id,
            "user_id": user_id
        })

        if not path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning path not found"
            )

        updated_at = datetime.utcnow()
        db.learning_paths.update_one(
            {"_id": path.get("_id")},
            {
                "$set": {
                    f"lesson_progress.{payload.lesson_id}": payload.status,
                    "updated_at": updated_at
                }
            }
        )

        return LessonProgressResponse(
            path_id=payload.path_id,
            lesson_id=payload.lesson_id,
            status=payload.status,
            updated_at=updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating lesson progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update lesson progress"
        )


@router.get("/{path_id}", status_code=status.HTTP_200_OK)
def get_learning_path_detail(
    path_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a single learning path by path_id for the current user.
    """
    user_id = str(current_user.get("_id", ""))
    logger.info(f"Learning path detail requested: user={user_id}, path_id={path_id}")

    try:
        from backend.app.database.mongo import get_db
        db = get_db()

        path = db.learning_paths.find_one(
            {"path_id": path_id, "user_id": user_id}
        )

        if not path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning path not found"
            )

        lesson_progress = path.get("lesson_progress", {})
        path["curriculum"] = _apply_lesson_progress(
            path.get("curriculum"),
            lesson_progress
        )

        if "_id" in path:
            path["_id"] = str(path["_id"])

        return {
            "success": True,
            "path": path
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching learning path detail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch learning path detail"
        )