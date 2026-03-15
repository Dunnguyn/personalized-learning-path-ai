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
import re

from backend.app.services.learning_path_service import (
    generate_learning_path,
    generate_lesson_mcq_questions,
    calculate_min_correct_required
)
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
MIN_CORRECT_TO_PASS = 7


def _save_confidence_event(
    db,
    user_id: str,
    path_id: str,
    lesson_id: str,
    lesson_status: str,
    assessment_result: Optional[dict],
    timestamp: datetime
) -> None:
    """Store confidence event for time-series analytics."""
    if not assessment_result:
        return

    try:
        confidence_value = float(assessment_result.get("score_percent", 0.0) or 0.0) / 100.0
        confidence_value = max(0.0, min(1.0, confidence_value))
        db.confidence_events.insert_one({
            "user_id": user_id,
            "path_id": path_id,
            "lesson_id": lesson_id,
            "status": lesson_status,
            "source": "lesson_assessment",
            "confidence": round(confidence_value, 4),
            "assessment_result": {
                "attempted_questions": int(assessment_result.get("attempted_questions", 0) or 0),
                "correct_answers": int(assessment_result.get("correct_answers", 0) or 0),
                "required_questions": int(assessment_result.get("required_questions", 10) or 10),
                "min_correct_required": int(assessment_result.get("min_correct_required", MIN_CORRECT_TO_PASS) or MIN_CORRECT_TO_PASS),
                "passed": bool(assessment_result.get("passed", False)),
                "score_percent": float(assessment_result.get("score_percent", 0.0) or 0.0)
            },
            "created_at": timestamp
        })
    except Exception as e:
        logger.warning(f"Failed to persist confidence event: {e}")


def _build_legacy_assessment_questions(lesson_title: str, required: int = 10) -> List[dict]:
    logger.warning("Legacy assessment requested for lesson '%s' but question fallback is disabled", lesson_title)
    return []


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
            assessment = lesson.get("assessment") or {}
            required = int(assessment.get("required_questions", 10) or 10)
            attempted = int(assessment.get("attempted_questions", 0) or 0)
            if attempted > required:
                attempted = required
            questions = assessment.get("questions", [])
            if not questions:
                questions = _build_legacy_assessment_questions(lesson.get("title") or "Bai hoc", required)
            min_correct_required = int(
                assessment.get("min_correct_required", calculate_min_correct_required(required)) or
                calculate_min_correct_required(required)
            )
            lesson["assessment"] = {
                "required_questions": required,
                "attempted_questions": attempted,
                "completed": bool(assessment.get("completed", False)) or lesson.get("status") == "complete",
                "generation": int(assessment.get("generation", 0) or 0),
                "correct_answers": int(assessment.get("correct_answers", 0) or 0),
                "min_correct_required": min_correct_required,
                "passed": bool(assessment.get("passed", False)),
                "score_percent": float(assessment.get("score_percent", 0.0) or 0.0),
                "questions": questions,
                "question_results": assessment.get("question_results", []) or []
            }
    return curriculum


def _restart_lesson_assessment(
    curriculum: Optional[List[dict]],
    lesson_id: str,
    lesson_status: str,
    level: str
) -> tuple[Optional[List[dict]], Optional[dict]]:
    if not curriculum:
        return curriculum, None

    updated = []
    found = False

    for chapter in curriculum:
        new_chapter = {**chapter, "lessons": []}
        for lesson in chapter.get("lessons", []):
            if lesson.get("lesson_id") != lesson_id:
                new_chapter["lessons"].append(lesson)
                continue

            found = True
            lesson_copy = {**lesson}
            assessment = lesson_copy.get("assessment") or {}
            required = int(assessment.get("required_questions", 10) or 10)
            next_generation = int(assessment.get("generation", 0) or 0) + 1
            new_questions = generate_lesson_mcq_questions(
                concept=lesson_copy.get("title") or "Bai hoc",
                level=level,
                lesson_summary=lesson_copy.get("summary") or "",
                lesson_resources=lesson_copy.get("resources") or [],
                num_questions=required,
                variation_seed=next_generation,
                chapter_id=chapter.get("chapter_id")
            )
            actual_required = len(new_questions)
            min_correct_required = calculate_min_correct_required(actual_required)

            lesson_copy["status"] = lesson_status
            lesson_copy["assessment"] = {
                "required_questions": actual_required,
                "attempted_questions": 0,
                "completed": False,
                "generation": next_generation,
                "correct_answers": 0,
                "min_correct_required": min_correct_required,
                "passed": False,
                "score_percent": 0.0,
                "questions": new_questions,
                "question_results": []
            }
            new_chapter["lessons"].append(lesson_copy)
        updated.append(new_chapter)

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found in learning path"
        )

    return updated, {
        "attempted_questions": 0,
        "correct_answers": 0,
        "required_questions": actual_required,
        "min_correct_required": min_correct_required,
        "passed": False,
        "score_percent": 0.0,
        "question_results": [],
        "restarted": True
    }


def _normalize_tokens(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _is_answer_correct(user_answer: str, expected_answer: str) -> bool:
    user_tokens = set(_normalize_tokens(user_answer))
    expected_tokens = set(_normalize_tokens(expected_answer))

    if not expected_tokens:
        return bool(user_tokens)
    if not user_tokens:
        return False

    stop_words = {
        "the", "a", "an", "is", "are", "to", "in", "on", "for", "of", "and", "or",
        "la", "gi", "mot", "nhung", "cac", "trong", "voi", "dua", "theo", "noi", "dung"
    }
    user_core = {t for t in user_tokens if t not in stop_words}
    expected_core = {t for t in expected_tokens if t not in stop_words}

    if not expected_core:
        expected_core = expected_tokens
    if not user_core:
        user_core = user_tokens

    overlap = user_core & expected_core
    overlap_ratio = len(overlap) / max(len(expected_core), 1)

    expected_text = (expected_answer or "").strip().lower()
    user_text = (user_answer or "").strip().lower()
    contains_expected = expected_text and expected_text[:80] in user_text

    return overlap_ratio >= 0.35 or bool(contains_expected)


def _is_option_correct(user_answer: str, question: dict) -> bool:
    selected = (user_answer or "").strip().upper()
    correct_option = str(question.get("correct_option", "")).strip().upper()
    if selected and correct_option:
        return selected == correct_option

    expected_answer = str(question.get("answer", ""))
    return _is_answer_correct(user_answer, expected_answer)


def _grade_lesson_answers(assessment: dict, answered_questions: Optional[List[str]]) -> dict:
    questions = assessment.get("questions", []) or []
    required = int(assessment.get("required_questions", 10) or 10)
    min_correct_required = int(
        assessment.get("min_correct_required", calculate_min_correct_required(required)) or
        calculate_min_correct_required(required)
    )
    answers = answered_questions or []

    attempted = 0
    correct = 0
    question_results = []

    for idx, question in enumerate(questions[:required]):
        user_answer = answers[idx].strip() if idx < len(answers) and isinstance(answers[idx], str) else ""
        is_correct = False
        if user_answer:
            attempted += 1
            is_correct = _is_option_correct(user_answer, question)
        if is_correct:
            correct += 1

        question_results.append({
            "question_id": question.get("question_id"),
            "selected_answer": user_answer,
            "is_correct": is_correct,
            "correct_option": str(question.get("correct_option", "")).strip().upper(),
            "correct_answer": str(question.get("answer", "")),
            "explanation": str(question.get("explanation", "")),
        })

    score_percent = round((correct / max(required, 1)) * 100, 2)
    passed = correct >= min_correct_required and attempted >= required

    return {
        "required_questions": required,
        "attempted_questions": min(attempted, required),
        "correct_answers": correct,
        "min_correct_required": min_correct_required,
        "passed": passed,
        "score_percent": score_percent,
        "question_results": question_results
    }


def _update_lesson_assessment_progress(
    curriculum: Optional[List[dict]],
    lesson_id: str,
    lesson_status: str,
    answered_questions: Optional[List[str]]
) -> tuple[Optional[List[dict]], Optional[dict]]:
    if not curriculum:
        return curriculum, None

    updated = []
    found = False
    grading_result = None

    for chapter in curriculum:
        new_chapter = {**chapter, "lessons": []}
        for lesson in chapter.get("lessons", []):
            if lesson.get("lesson_id") != lesson_id:
                new_chapter["lessons"].append(lesson)
                continue

            found = True
            lesson_copy = {**lesson}
            assessment = lesson_copy.get("assessment") or {}
            required = int(assessment.get("required_questions", 10) or 10)
            min_correct_required = int(
                assessment.get("min_correct_required", calculate_min_correct_required(required)) or
                calculate_min_correct_required(required)
            )
            scored = _grade_lesson_answers(assessment, answered_questions)
            existing_attempted = int(assessment.get("attempted_questions", 0) or 0)
            if scored["attempted_questions"] < existing_attempted:
                scored["attempted_questions"] = existing_attempted
            if scored["attempted_questions"] > required:
                scored["attempted_questions"] = required

            existing_correct = int(assessment.get("correct_answers", 0) or 0)
            if scored["correct_answers"] < existing_correct:
                scored["correct_answers"] = existing_correct

            scored["score_percent"] = round((scored["correct_answers"] / max(required, 1)) * 100, 2)
            scored["passed"] = scored["correct_answers"] >= min_correct_required and scored["attempted_questions"] >= required

            if lesson_status == "complete" and scored["attempted_questions"] < required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You must answer all {required} assessment questions before completing this lesson"
                )

            if lesson_status == "complete" and not scored["passed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Assessment not passed: {scored['correct_answers']}/{required} correct. Minimum required is {min_correct_required}."
                )

            visible_question_results = scored.get("question_results", [])

            lesson_copy["status"] = lesson_status
            lesson_copy["assessment"] = {
                "required_questions": required,
                "attempted_questions": scored["attempted_questions"],
                "completed": lesson_status == "complete",
                "generation": int(assessment.get("generation", 0) or 0),
                "correct_answers": scored["correct_answers"],
                "min_correct_required": min_correct_required,
                "passed": scored["passed"],
                "score_percent": scored["score_percent"],
                "questions": assessment.get("questions", []),
                "question_results": visible_question_results
            }
            grading_result = {
                "attempted_questions": scored["attempted_questions"],
                "correct_answers": scored["correct_answers"],
                "required_questions": required,
                "min_correct_required": min_correct_required,
                "passed": scored["passed"],
                "score_percent": scored["score_percent"],
                "question_results": visible_question_results
            }
            new_chapter["lessons"].append(lesson_copy)
        updated.append(new_chapter)

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found in learning path"
        )

    return updated, grading_result


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
        if payload.restart_assessment:
            updated_curriculum, assessment_result = _restart_lesson_assessment(
                path.get("curriculum"),
                payload.lesson_id,
                payload.status,
                path.get("level", "intermediate")
            )
        else:
            updated_curriculum, assessment_result = _update_lesson_assessment_progress(
                path.get("curriculum"),
                payload.lesson_id,
                payload.status,
                payload.answered_questions
            )

        db.learning_paths.update_one(
            {"_id": path.get("_id")},
            {
                "$set": {
                    f"lesson_progress.{payload.lesson_id}": payload.status,
                    "curriculum": updated_curriculum,
                    "updated_at": updated_at
                }
            }
        )

        if not (assessment_result or {}).get("restarted"):
            _save_confidence_event(
                db=db,
                user_id=user_id,
                path_id=payload.path_id,
                lesson_id=payload.lesson_id,
                lesson_status=payload.status,
                assessment_result=assessment_result,
                timestamp=updated_at
            )

        return LessonProgressResponse(
            path_id=payload.path_id,
            lesson_id=payload.lesson_id,
            status=payload.status,
            updated_at=updated_at,
            assessment_result=assessment_result
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
