from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional

from backend.app.api.schemas import AskRequest, AskResponse
from backend.app.services.ai_service import ai_tutor_service
from backend.app.api.auth import get_current_user

import logging

logger = logging.getLogger(__name__)

# =========================
# ROUTER
# =========================
router = APIRouter(prefix="/ask", tags=["Ask AI"])


# =========================
# MAIN ENDPOINT: ASK AI
# =========================
@router.post("/", response_model=AskResponse)
def ask_ai(request: AskRequest, current_user=Depends(get_current_user)):
    """
    AI Tutor endpoint with full orchestration:
    - Answer question using RAG
    - Detect learning concept (semantic + rule-based)
    - Score learner confidence
    - Update learning progress
    - Make adaptive mode decision
    - Suggest adaptive learning path
    
    Requires: authenticated user (must match user_id)
    
    Request body:
    ```json
    {
        "user_id": 1,
        "question": "What is a Python list?",
        "goal": "Python",
        "level": "beginner",
        "completed": ["variables", "strings"]
    }
    ```
    
    Response:
    ```json
    {
        "success": true,
        "answer": {
            "text": "A Python list is...",
            "confidence": 0.87,
            "sources": [...]
        },
        "learning_path": [...],
        "adaptive": {
            "mode": "normal",
            "can_unlock_next": true,
            "practice_recommendation": {...}
        },
        "concept_detected": {
            "concept_id": 5,
            "concept_name": "Python List",
            "method": "semantic"
        },
        "progress": {
            "mastery": 0.75,
            "confidence": 0.87,
            "attempts": 3
        }
    }
    ```
    """
    
    # Ownership check
    if current_user["user_id"] != request.user_id:
        logger.warning(f"Unauthorized ask attempt: auth_user={current_user['user_id']}, request_user={request.user_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Basic input validation
    if not request.question or len(request.question.strip()) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question is required")
    
    if len(request.question) > 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question too long (max 2000 chars)")
    
    if not request.goal or len(request.goal) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid goal")
    
    if request.completed and len(request.completed) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many completed concepts")

    try:
        # Call orchestration service
        response = ai_tutor_service.ask_ai(
            user_id=request.user_id,
            question=request.question,
            goal=request.goal,
            level=request.level.value if hasattr(request.level, "value") else request.level,
            completed=request.completed or []
        )
        
        logger.info(f"Ask completed successfully: user={request.user_id}, concept={response.get('concept_detected', {}).get('concept_name')}")
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in ask_ai: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again."
        )


# =========================
# ENDPOINT: GET ADAPTIVE STATUS
# =========================
@router.get(
    "/adaptive-status",
    summary="Get adaptive learning status for a concept"
)
def get_adaptive_status(
    user_id: int = Query(..., ge=1, description="User ID"),
    concept_id: int = Query(..., ge=1, description="Concept ID"),
    current_user=Depends(get_current_user)
):
    """
    Get current adaptive learning status for a specific concept.
    
    Returns:
    - learning_mode (remedial/normal/advanced)
    - mastery & confidence scores
    - whether next concept can be unlocked
    - practice recommendations
    
    Requires: authenticated user
    
    Example response:
    ```json
    {
        "mode": "normal",
        "mastery": 0.75,
        "confidence": 0.7,
        "attempts": 5,
        "combined_score": 0.725,
        "can_unlock_next": true,
        "recommended_difficulty": 6,
        "practice_recommendation": {
            "practice_type": "spaced_review",
            "intensity": 2,
            "urgency": "optional",
            "description": "Periodic review to maintain mastery"
        }
    }
    ```
    """
    
    # Ownership check
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    try:
        from backend.app.services.adaptive_engine import adaptive_decision_summary
        from backend.app.database.mongo import db
        
        # Fetch progress
        progress = db.progress.find_one({
            "user_id": user_id,
            "concept_id": concept_id
        })
        
        if not progress:
            logger.info(f"No progress found: user={user_id}, concept={concept_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No progress found for this concept. Start learning first!"
            )
        
        mastery = progress.get("mastery", 0.0)
        confidence = progress.get("confidence", 0.5)
        attempts = progress.get("total_attempts", 0)
        
        # Get adaptive summary
        summary = adaptive_decision_summary(mastery, confidence, attempts)
        
        logger.info(f"Adaptive status: user={user_id}, concept={concept_id}, mode={summary['mode']}")
        
        return summary
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting adaptive status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve adaptive status"
        )


# =========================
# ENDPOINT: BATCH CONCEPT DETECTION
# =========================
@router.post(
    "/detect-concepts",
    summary="Detect concepts from multiple questions"
)
def detect_concepts_batch(
    questions: List[str] = Query(..., description="List of questions to analyze"),
    current_user=Depends(get_current_user)
):
    """
    Batch detect concepts from multiple questions.
    
    Useful for:
    - Pre-analyzing questions before answering
    - Understanding what concepts a learner needs help with
    - Planning learning paths
    
    Requires: authenticated user
    
    Query parameters:
    - `questions`: list of question strings
    
    Example:
    ```
    GET /ask/detect-concepts?questions=What%20is%20a%20list&questions=How%20to%20use%20loops
    ```
    
    Response:
    ```json
    {
        "detected_concepts": [
            {
                "concept_id": 5,
                "concept_name": "Python List",
                "score": 0.92,
                "method": "semantic"
            },
            {
                "concept_id": 8,
                "concept_name": "Python Loop",
                "score": null,
                "method": "rule-based"
            }
        ],
        "total_detected": 2
    }
    ```
    """
    
    if not questions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Questions list required")
    
    if len(questions) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Max 20 questions per request")
    
    try:
        from backend.app.services.ai_service import concept_detector
        
        detected = []
        for question in questions:
            if not question or len(question) > 500:
                continue
            
            concept = concept_detector.detect(question)
            detected.append({
                "question": question,
                "concept": concept
            })
        
        logger.info(f"Batch detection: user={current_user['user_id']}, questions={len(questions)}, detected={sum(1 for d in detected if d['concept'])}")
        
        return {
            "detected_concepts": detected,
            "total_questions": len(questions),
            "total_detected": sum(1 for d in detected if d['concept'] is not None)
        }
    
    except Exception as e:
        logger.exception(f"Batch detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not detect concepts"
        )


# =========================
# ENDPOINT: RECOMMEND NEXT CONCEPTS
# =========================
@router.get(
    "/recommend-concepts",
    summary="Get concept recommendations without answering"
)
def recommend_next_concepts(
    user_id: int = Query(..., ge=1, description="User ID"),
    goal: str = Query(..., min_length=1, max_length=200, description="Learning goal"),
    level: str = Query(..., description="Current level (beginner/intermediate/advanced)"),
    limit: int = Query(5, ge=1, le=20, description="Max recommendations"),
    current_user=Depends(get_current_user)
):
    """
    Get personalized concept recommendations for browsing/learning plan.
    Does NOT require answering a question.
    
    Useful for:
    - Exploring what to learn next
    - Planning learning journey
    - Understanding content structure
    
    Requires: authenticated user (must match user_id)
    
    Response:
    ```json
    {
        "success": true,
        "recommended_concepts": [
            {
                "concept_id": 1,
                "concept_name": "Variables",
                "difficulty": 1,
                "mode": "normal",
                "priority_score": 0.9,
                "resources": [...]
            },
            ...
        ]
    }
    ```
    """
    
    # Ownership check
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    # Validate level
    valid_levels = ["beginner", "intermediate", "advanced"]
    if level not in valid_levels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid level. Must be one of: {', '.join(valid_levels)}"
        )
    
    try:
        from backend.app.services.ai_service import ai_tutor_service
        
        result = ai_tutor_service._generate_adaptive_path(
            user_id=user_id,
            goal=goal,
            level=level,
            learning_mode="normal"
        )
        
        # Limit results
        result = result[:limit]
        
        logger.info(f"Concept recommendations: user={user_id}, goal={goal}, count={len(result)}")
        
        return {
            "success": True,
            "recommended_concepts": result,
            "count": len(result)
        }
    
    except Exception as e:
        logger.exception(f"Concept recommendation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate recommendations"
        )


# =========================
# ENDPOINT: CONCEPT DETAILS
# =========================
@router.get(
    "/concept/{concept_id}",
    summary="Get detailed information about a concept"
)
def get_concept_details(
    concept_id: int = Query(..., ge=1),
    user_id: int = Query(..., ge=1),
    current_user=Depends(get_current_user)
):
    """
    Get detailed information about a specific concept.
    
    Includes:
    - Concept metadata (name, difficulty, description)
    - User's progress on this concept
    - Recommended resources
    - Prerequisite concepts
    - Prerequisite for concepts
    
    Requires: authenticated user
    """
    
    if current_user["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    try:
        from backend.app.database.mongo import db
        
        # Get concept
        concept = db.concepts.find_one(
            {"concept_id": concept_id},
            {"_id": 0}
        )
        
        if not concept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found")
        
        # Get user progress
        progress = db.progress.find_one(
            {"user_id": user_id, "concept_id": concept_id},
            {"_id": 0}
        )
        
        # Get prerequisites
        prerequisites = list(db.prerequisites.find(
            {"to_concept_id": concept_id},
            {"_id": 0, "from_concept_id": 1}
        ))
        
        prereq_concepts = []
        for p in prerequisites:
            prereq = db.concepts.find_one(
                {"concept_id": p["from_concept_id"]},
                {"concept_id": 1, "concept_name": 1}
            )
            if prereq:
                prereq_concepts.append(prereq)
        
        # Get resources
        resources = list(db.resources.find(
            {"concept_id": concept_id},
            {"_id": 0, "title": 1, "source": 1, "level": 1, "url": 1}
        ).limit(10))
        
        logger.info(f"Concept details retrieved: user={user_id}, concept={concept_id}")
        
        return {
            "concept": concept,
            "progress": progress or {"mastery": 0, "confidence": 0.5, "total_attempts": 0},
            "prerequisites": prereq_concepts,
            "resources": resources
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving concept details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve concept details"
        )


# =========================
# OPTIONAL: DEBUG ENDPOINT (remove in production)
# =========================
@router.post(
    "/debug/concept-detection",
    summary="Debug concept detection (development only)"
)
def debug_concept_detection(
    question: str = Query(..., description="Question to analyze"),
    current_user=Depends(get_current_user)
):
    """
    Debug concept detection strategies.
    Returns scores from all 3 detection methods.
    (Remove this endpoint in production)
    """
    
    if not question or len(question) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    
    try:
        from backend.app.services.ai_service import concept_detector
        import os
        
        # Only allow in development
        if os.getenv("ENV") == "production":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        
        semantic = concept_detector.detect_semantic(question)
        rule_based = concept_detector.detect_rule_based(question)
        fallback = concept_detector.detect_fallback()
        
        logger.debug(f"Debug detection: semantic={semantic}, rule_based={rule_based}")
        
        return {
            "question": question,
            "semantic": semantic,
            "rule_based": rule_based,
            "fallback": fallback,
            "final_result": concept_detector.detect(question)
        }
    
    except Exception as e:
        logger.exception(f"Debug error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)