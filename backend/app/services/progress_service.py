from datetime import datetime
from typing import Optional, Dict
import logging
import os

from backend.app.database.mongo import db

logger = logging.getLogger(__name__)

# ==================================================
# CONFIG
# ==================================================
ALPHA = float(os.getenv("PROGRESS_ALPHA", "0.3"))  # EMA learning rate
MIN_CONFIDENCE_THRESHOLD = float(os.getenv("PROGRESS_MIN_CONFIDENCE", "0.3"))  # Ignore very low confidence
MASTERY_COMPLETE_THRESHOLD = float(os.getenv("PROGRESS_MASTERY_COMPLETE", "0.8"))  # Concept complete
MASTERY_PROFICIENT_THRESHOLD = float(os.getenv("PROGRESS_MASTERY_PROFICIENT", "0.6"))  # Proficient


# ==================================================
# UTILITY FUNCTIONS
# ==================================================
def get_progress(user_id: int, concept_id: int) -> Optional[Dict]:
    """
    Fetch user's progress on a concept.
    
    Returns:
        Dict with fields: mastery, confidence, total_attempts, successful_attempts, last_updated
        None if no progress found
    """
    try:
        record = db.progress.find_one(
            {"user_id": user_id, "concept_id": concept_id},
            {"_id": 0}
        )
        return record
    except Exception as e:
        logger.exception(f"Error fetching progress: {e}")
        return None


def get_user_progress_summary(user_id: int) -> Dict:
    """
    Get summary of user's overall progress across all concepts.
    
    Returns:
        {
            "user_id": int,
            "total_concepts_started": int,
            "total_concepts_completed": int,
            "average_mastery": float,
            "average_confidence": float,
            "total_attempts": int,
            "concepts": [...]
        }
    """
    try:
        progress_list = list(db.progress.find(
            {"user_id": user_id},
            {"_id": 0}
        ))
        
        if not progress_list:
            return {
                "user_id": user_id,
                "total_concepts_started": 0,
                "total_concepts_completed": 0,
                "average_mastery": 0.0,
                "average_confidence": 0.0,
                "total_attempts": 0,
                "concepts": []
            }
        
        completed = sum(
            1 for p in progress_list
            if p.get("mastery", 0) >= MASTERY_COMPLETE_THRESHOLD
        )
        
        avg_mastery = sum(p.get("mastery", 0) for p in progress_list) / len(progress_list) if progress_list else 0
        avg_confidence = sum(p.get("confidence", 0.5) for p in progress_list) / len(progress_list) if progress_list else 0
        total_attempts = sum(p.get("total_attempts", 0) for p in progress_list)
        
        return {
            "user_id": user_id,
            "total_concepts_started": len(progress_list),
            "total_concepts_completed": completed,
            "average_mastery": round(avg_mastery, 3),
            "average_confidence": round(avg_confidence, 3),
            "total_attempts": total_attempts,
            "concepts": progress_list
        }
    
    except Exception as e:
        logger.exception(f"Error getting progress summary for user {user_id}: {e}")
        return {
            "user_id": user_id,
            "error": str(e),
            "total_concepts_started": 0
        }


def get_concept_progress(concept_id: int) -> Dict:
    """
    Get aggregate progress for a concept across all users.
    Useful for analytics/admin.
    """
    try:
        progress_list = list(db.progress.find(
            {"concept_id": concept_id},
            {"_id": 0}
        ))
        
        if not progress_list:
            return {
                "concept_id": concept_id,
                "total_users": 0,
                "avg_mastery": 0.0,
                "avg_attempts": 0.0
            }
        
        avg_mastery = sum(p.get("mastery", 0) for p in progress_list) / len(progress_list)
        avg_attempts = sum(p.get("total_attempts", 0) for p in progress_list) / len(progress_list)
        
        return {
            "concept_id": concept_id,
            "total_users": len(progress_list),
            "avg_mastery": round(avg_mastery, 3),
            "avg_attempts": round(avg_attempts, 1),
            "users": progress_list
        }
    
    except Exception as e:
        logger.exception(f"Error getting concept progress: {e}")
        return {"concept_id": concept_id, "error": str(e)}


# ==================================================
# MAIN FUNCTION: UPDATE PROGRESS
# ==================================================
def update_progress_with_confidence(
    user_id: int,
    concept_id: int,
    confidence: float
) -> Dict:
    """
    Update learning progress using EMA (Exponential Moving Average).

    Algorithm:
        new_mastery = old_mastery * (1 - α) + confidence * α
    
    where α is the learning rate (default 0.3).
    
    Parameters
    ----------
    user_id : int
        Learner ID
    concept_id : int
        Concept ID
    confidence : float
        AI-evaluated confidence [0.0, 1.0]
    
    Returns
    -------
    Dict : updated progress record with fields:
        - mastery: new mastery score
        - confidence: current confidence
        - total_attempts: total number of updates
        - successful_attempts: attempts with confidence >= MIN_CONFIDENCE_THRESHOLD
        - status: "not_started" | "in_progress" | "proficient" | "complete"
        - last_updated: timestamp
    
    Raises
    ------
    ValueError : if inputs invalid
    Exception : if DB operation fails (logged, not re-raised)
    """
    
    logger.debug(f"Updating progress: user={user_id}, concept={concept_id}, confidence={confidence}")
    
    # ---------- 1. VALIDATE INPUT ----------
    if user_id <= 0 or concept_id <= 0:
        raise ValueError("user_id and concept_id must be positive integers")
    
    confidence = max(0.0, min(confidence, 1.0))
    
    # ---------- 2. FETCH EXISTING PROGRESS ----------
    try:
        record = db.progress.find_one(
            {"user_id": user_id, "concept_id": concept_id},
            {"_id": 0}
        )
    except Exception as e:
        logger.exception(f"Error fetching existing progress: {e}")
        raise
    
    old_mastery = record.get("mastery", 0.0) if record else 0.0
    old_confidence = record.get("confidence", 0.5) if record else 0.5
    total_attempts = (record.get("total_attempts", 0) if record else 0) + 1
    successful_attempts = record.get("successful_attempts", 0) if record else 0
    
    # Count successful attempt if confidence high enough
    if confidence >= MIN_CONFIDENCE_THRESHOLD:
        successful_attempts += 1
    
    # ---------- 3. EMA UPDATE ----------
    new_mastery = old_mastery * (1 - ALPHA) + confidence * ALPHA
    new_mastery = round(new_mastery, 3)
    
    # ---------- 4. DETERMINE STATUS ----------
    if new_mastery >= MASTERY_COMPLETE_THRESHOLD:
        status = "complete"
    elif new_mastery >= MASTERY_PROFICIENT_THRESHOLD:
        status = "proficient"
    elif total_attempts > 0:
        status = "in_progress"
    else:
        status = "not_started"
    
    # ---------- 5. PERSIST ----------
    now = datetime.utcnow()
    
    try:
        result = db.progress.update_one(
            {"user_id": user_id, "concept_id": concept_id},
            {"$set": {
                "user_id": user_id,
                "concept_id": concept_id,
                "mastery": new_mastery,
                "confidence": round(confidence, 3),
                "total_attempts": total_attempts,
                "successful_attempts": successful_attempts,
                "success_rate": round(successful_attempts / total_attempts, 3) if total_attempts > 0 else 0,
                "status": status,
                "last_updated": now,
                "updated_at": now
            }},
            upsert=True
        )
        
        logger.info(
            f"Progress updated: user={user_id}, concept={concept_id}, "
            f"mastery={old_mastery}->{new_mastery}, confidence={confidence}, "
            f"attempts={total_attempts}, status={status}"
        )
        
        # Fetch and return the updated record
        updated = db.progress.find_one(
            {"user_id": user_id, "concept_id": concept_id},
            {"_id": 0}
        )
        
        return updated or {
            "user_id": user_id,
            "concept_id": concept_id,
            "mastery": new_mastery,
            "confidence": round(confidence, 3),
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "status": status,
            "last_updated": now
        }
    
    except Exception as e:
        logger.exception(f"Error persisting progress: {e}")
        raise


# ==================================================
# BATCH UPDATE
# ==================================================
def update_progress_batch(
    updates: list
) -> Dict:
    """
    Update progress for multiple concept-confidence pairs.
    
    Parameters
    ----------
    updates : list
        [{user_id, concept_id, confidence}, ...]
    
    Returns
    -------
    Dict : {"success": count, "failed": count, "errors": [...]}
    """
    success = 0
    failed = 0
    errors = []
    
    for update in updates:
        try:
            user_id = update.get("user_id")
            concept_id = update.get("concept_id")
            confidence = update.get("confidence", 0.5)
            
            update_progress_with_confidence(user_id, concept_id, confidence)
            success += 1
        except Exception as e:
            logger.warning(f"Batch update failed for {update}: {e}")
            failed += 1
            errors.append({"update": update, "error": str(e)})
    
    logger.info(f"Batch update complete: success={success}, failed={failed}")
    
    return {
        "success": success,
        "failed": failed,
        "errors": errors
    }


# ==================================================
# RESET/CLEANUP
# ==================================================
def reset_user_progress(user_id: int) -> Dict:
    """
    Reset all progress for a user (useful for restart/testing).
    """
    try:
        result = db.progress.delete_many({"user_id": user_id})
        logger.info(f"Reset progress for user {user_id}: deleted {result.deleted_count} records")
        
        return {
            "success": True,
            "user_id": user_id,
            "deleted_count": result.deleted_count
        }
    except Exception as e:
        logger.exception(f"Error resetting progress: {e}")
        return {
            "success": False,
            "user_id": user_id,
            "error": str(e)
        }


def reset_concept_progress(concept_id: int) -> Dict:
    """
    Reset all progress for a concept across all users (admin only).
    """
    try:
        result = db.progress.delete_many({"concept_id": concept_id})
        logger.warning(f"Reset progress for concept {concept_id}: deleted {result.deleted_count} records")
        
        return {
            "success": True,
            "concept_id": concept_id,
            "deleted_count": result.deleted_count
        }
    except Exception as e:
        logger.exception(f"Error resetting concept progress: {e}")
        return {
            "success": False,
            "concept_id": concept_id,
            "error": str(e)
        }


# ==================================================
# ANALYTICS
# ==================================================
def get_progress_stats(user_id: int, concept_id: Optional[int] = None) -> Dict:
    """
    Get detailed progress statistics.
    """
    try:
        query = {"user_id": user_id}
        if concept_id:
            query["concept_id"] = concept_id
        
        progress = db.progress.find_one(query, {"_id": 0})
        
        if not progress:
            return {"user_id": user_id, "concept_id": concept_id, "status": "no_progress"}
        
        total_attempts = progress.get("total_attempts", 0)
        successful_attempts = progress.get("successful_attempts", 0)
        
        return {
            "user_id": user_id,
            "concept_id": concept_id,
            "mastery": progress.get("mastery", 0),
            "confidence": progress.get("confidence", 0.5),
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "success_rate": (successful_attempts / total_attempts) if total_attempts > 0 else 0,
            "status": progress.get("status", "unknown"),
            "last_updated": progress.get("last_updated"),
            "days_active": _days_since(progress.get("last_updated"))
        }
    
    except Exception as e:
        logger.exception(f"Error getting progress stats: {e}")
        return {"error": str(e)}


def _days_since(dt: Optional[datetime]) -> int:
    """Calculate days since datetime."""
    if not dt:
        return 0
    return (datetime.utcnow() - dt).days