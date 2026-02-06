from fastapi import APIRouter, Query, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import logging

from backend.app.api.schemas import LevelEnum
from backend.app.api.auth import get_current_user
from backend.app.database.mongo import db

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


class PersonalizedRecommendationResponse(BaseModel):
    user_id: int
    goal: str
    level: str
    recommended_resources: List[ResourceItem]
    completed_concepts: int
    total_concepts: int
    progress_percentage: float
    message: str


class ConceptProgressItem(BaseModel):
    concept_id: int
    concept_name: str
    difficulty: int
    mastery: float
    status: str  # "completed", "in-progress", "not-started"


class LearningProgressResponse(BaseModel):
    user_id: int
    goal: str
    concepts: List[ConceptProgressItem]
    overall_mastery: float
    message: str


# =========================
# HELPER
# =========================
def enum_to_string(value) -> str:
    if hasattr(value, "value"):
        return value.value
    return str(value)


# =========================
# GET PERSONALIZED RECOMMENDATIONS
# =========================
@router.get(
    "/resources",
    response_model=PersonalizedRecommendationResponse,
    summary="Get personalized learning resource recommendations"
)
def get_personalized_resources(
    user_id: int = Query(..., ge=1, description="User ID"),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    level: LevelEnum = Query(LevelEnum.beginner, description="Current level"),
    limit: int = Query(10, ge=1, le=50, description="Max recommendations"),
    current_user=Depends(get_current_user)
):
    """
    Get personalized learning resource recommendations based on:
    - Learning goal & topic
    - Current level
    - Completed concepts (progress)
    - Resource relevance & type
    
    Requires: authenticated user (can only get own recommendations)
    """
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    try:
        level_str = enum_to_string(level)
        
        # Get user's progress
        progress_docs = list(db.progress.find({"user_id": user_id}))
        mastery_map = {p["concept_id"]: p.get("mastery", 0) for p in progress_docs}
        completed_ids = [p["concept_id"] for p in progress_docs if p.get("mastery", 0) >= 0.8]
        
        # Find concepts for goal
        goal_concepts = list(db.concepts.find(
            {"topic": {"$regex": goal, "$options": "i"}},
            {"concept_id": 1, "concept_name": 1, "difficulty": 1, "topic": 1}
        ).sort("difficulty", 1))  # Sort by difficulty ascending
        
        if not goal_concepts:
            return {
                "user_id": user_id,
                "goal": goal,
                "level": level_str,
                "recommended_resources": [],
                "completed_concepts": 0,
                "total_concepts": 0,
                "progress_percentage": 0,
                "message": f"No concepts found for goal: {goal}"
            }
        
        goal_concept_ids = [c["concept_id"] for c in goal_concepts]
        next_concepts = [c for c in goal_concepts if c["concept_id"] not in completed_ids]
        
        if not next_concepts:
            return {
                "user_id": user_id,
                "goal": goal,
                "level": level_str,
                "recommended_resources": [],
                "completed_concepts": len(completed_ids),
                "total_concepts": len(goal_concepts),
                "progress_percentage": 100.0,
                "message": f"🎉 You have mastered all {goal} concepts!"
            }
        
        # Fetch resources for next concepts
        next_concept_ids = [c["concept_id"] for c in next_concepts[:5]]  # Top 5 next concepts
        
        resources = list(db.resources.find(
            {
                "concept_id": {"$in": next_concept_ids},
                "level": level_str
            }
        ).limit(limit * 2))
        
        # Fallback if not enough at this level
        if len(resources) < limit:
            level_fallback = {
                "beginner": "intermediate",
                "intermediate": "advanced",
                "advanced": "advanced"
            }
            fallback_level = level_fallback[level_str]
            resources.extend(list(db.resources.find(
                {
                    "concept_id": {"$in": next_concept_ids},
                    "level": fallback_level
                }
            ).limit(limit)))
        
        # Score resources
        recommended = []
        for res in resources[:limit]:
            concept = next((c for c in next_concepts if c["concept_id"] == res.get("concept_id")), None)
            if not concept:
                continue
            
            score = 0.7  # Base score
            
            # Level match bonus
            if res.get("level") == level_str:
                score += 0.15
            else:
                score += 0.05
            
            # Pedagogy bonus (video for beginners)
            if level_str == "beginner" and res.get("pedagogy_type") == "video":
                score += 0.1
            
            recommended.append({
                "resource_id": res.get("resource_id"),
                "title": res.get("title"),
                "source": res.get("source"),
                "level": res.get("level"),
                "topic": res.get("topic"),
                "url": res.get("url"),
                "reason": f"Recommended for: {concept.get('concept_name')}",
                "relevance_score": min(1.0, score)
            })
        
        recommended.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        progress_pct = (len(completed_ids) / len(goal_concepts) * 100) if goal_concepts else 0
        
        logger.info(
            f"Personalized recommendations: user={user_id}, goal={goal}, "
            f"level={level_str}, resources={len(recommended)}"
        )
        
        return {
            "user_id": user_id,
            "goal": goal,
            "level": level_str,
            "recommended_resources": recommended,
            "completed_concepts": len(completed_ids),
            "total_concepts": len(goal_concepts),
            "progress_percentage": round(progress_pct, 1),
            "message": f"Found {len(recommended)} recommended resources. Progress: {progress_pct:.1f}%"
        }
    
    except Exception as e:
        logger.exception(f"Error generating recommendations for user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not generate recommendations")


# =========================
# GET LEARNING PROGRESS FOR GOAL
# =========================
@router.get(
    "/progress",
    response_model=LearningProgressResponse,
    summary="Get learning progress for a specific goal"
)
def get_learning_progress(
    user_id: int = Query(..., ge=1, description="User ID"),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    current_user=Depends(get_current_user)
):
    """
    Get detailed progress on all concepts for a learning goal.
    
    Returns:
    - List of concepts with mastery level
    - Overall mastery percentage
    - Status of each concept (not-started, in-progress, completed)
    
    Requires: authenticated user
    """
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    try:
        # Get concepts for goal
        concepts = list(db.concepts.find(
            {"topic": {"$regex": goal, "$options": "i"}},
            {"concept_id": 1, "concept_name": 1, "difficulty": 1}
        ).sort("difficulty", 1))
        
        if not concepts:
            return {
                "user_id": user_id,
                "goal": goal,
                "concepts": [],
                "overall_mastery": 0,
                "message": f"No concepts found for goal: {goal}"
            }
        
        concept_ids = [c["concept_id"] for c in concepts]
        
        # Get user progress
        progress = list(db.progress.find(
            {
                "user_id": user_id,
                "concept_id": {"$in": concept_ids}
            }
        ))
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
            
            concept_progress.append({
                "concept_id": cid,
                "concept_name": concept.get("concept_name"),
                "difficulty": concept.get("difficulty", 0),
                "mastery": round(mastery, 2),
                "status": status
            })
            
            total_mastery += mastery
        
        overall = (total_mastery / len(concepts) * 100) if concepts else 0
        
        logger.info(f"Progress retrieved: user={user_id}, goal={goal}, overall={overall:.1f}%")
        
        return {
            "user_id": user_id,
            "goal": goal,
            "concepts": concept_progress,
            "overall_mastery": round(overall, 1),
            "message": f"Overall mastery for {goal}: {overall:.1f}%"
        }
    
    except Exception as e:
        logger.exception(f"Error getting progress for user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve progress")