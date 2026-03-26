"""
Progress Service: Track learner progress using exponential moving average (EMA).

Purpose:
- Maintain mastery scores per user per concept
- Update based on confidence scores (0-1 scale)
- Track attempt counts and success rates
- Generate status (not_started → in_progress → proficient → complete)

Algorithm:
- EMA formula: new_mastery = old_mastery * (1-α) + confidence * α
- α (alpha) = learning rate (default 0.3, configurable via env)
- Status transitions based on mastery thresholds (0.6 proficient, 0.8 complete)

All operations include:
- Input validation
- Comprehensive logging
- Error handling
- Environment-based configuration
"""

from datetime import datetime
from typing import Optional, Dict
import logging
import os

from backend.app.database.mongo import get_db
from bson import ObjectId

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ==================================================
# CONFIG
# ==================================================
ALPHA = float(os.getenv("PROGRESS_ALPHA", "0.3"))  # EMA learning rate
MIN_CONFIDENCE_THRESHOLD = float(
    os.getenv("PROGRESS_MIN_CONFIDENCE", "0.3")
)  # Ignore very low confidence
MASTERY_COMPLETE_THRESHOLD = float(
    os.getenv("PROGRESS_MASTERY_COMPLETE", "0.8")
)  # Concept complete
MASTERY_PROFICIENT_THRESHOLD = float(
    os.getenv("PROGRESS_MASTERY_PROFICIENT", "0.6")
)  # Proficient

logger.info(
    f"Progress service initialized: alpha={ALPHA}, "
    f"proficient_threshold={MASTERY_PROFICIENT_THRESHOLD}, "
    f"complete_threshold={MASTERY_COMPLETE_THRESHOLD}"
)


# ==================================================
# HELPER: STATUS CALCULATION
# ==================================================
def _calculate_status(mastery: float) -> str:
    """
    Calculate status based on mastery score.

    Args:
        mastery: Mastery score [0, 1]

    Returns:
        Status: "not_started" | "in_progress" | "proficient" | "complete"
    """
    if mastery >= MASTERY_COMPLETE_THRESHOLD:
        return "complete"
    elif mastery >= MASTERY_PROFICIENT_THRESHOLD:
        return "proficient"
    elif mastery > 0:
        return "in_progress"
    else:
        return "not_started"


# ==================================================
# UTILITY FUNCTIONS
# ==================================================
def get_progress(user_id: str, concept_id: int) -> Optional[Dict]:
    """
    Fetch user's progress on a concept.

    Args:
        user_id: MongoDB ObjectId as string
        concept_id: Concept ID (integer)

    Returns:
        Dict with fields: mastery, confidence, total_attempts, successful_attempts,
        success_rate, status, last_updated
        None if no progress found
    """
    logger.debug(f"Fetching progress: user={user_id}, concept={concept_id}")

    try:
        db = get_db()
        record = db.progress.find_one({"user_id": user_id, "concept_id": concept_id})

        if record:
            record["_id"] = str(record.get("_id", ""))

        return record

    except Exception as e:
        logger.exception(f"Error fetching progress: {e}")
        return None


def get_user_progress_summary(user_id: str) -> Dict:
    """
    Get summary of user's overall progress across all concepts.

    Args:
        user_id: MongoDB ObjectId as string

    Returns:
        Dict with:
        - user_id: str
        - total_concepts_started: int
        - total_concepts_completed: int
        - average_mastery: float
        - average_confidence: float
        - total_attempts: int
        - concepts: List[Dict] (per-concept progress)
    """
    logger.debug(f"Fetching progress summary: user={user_id}")

    try:
        db = get_db()
        progress_list = list(db.progress.find({"user_id": user_id}))

        if not progress_list:
            logger.info(f"No progress found for user {user_id}")
            return {
                "user_id": user_id,
                "total_concepts_started": 0,
                "total_concepts_completed": 0,
                "average_mastery": 0.0,
                "average_confidence": 0.0,
                "total_attempts": 0,
                "concepts": [],
            }

        # Calculate metrics
        completed = sum(
            1
            for p in progress_list
            if p.get("mastery", 0) >= MASTERY_COMPLETE_THRESHOLD
        )

        avg_mastery = sum(p.get("mastery", 0) for p in progress_list) / len(
            progress_list
        )
        avg_confidence = sum(p.get("confidence", 0.5) for p in progress_list) / len(
            progress_list
        )
        total_attempts = sum(p.get("total_attempts", 0) for p in progress_list)

        # Serialize ObjectIds
        for p in progress_list:
            if "_id" in p:
                p["_id"] = str(p["_id"])

        logger.info(
            f"Progress summary: user={user_id}, started={len(progress_list)}, completed={completed}"
        )

        return {
            "user_id": user_id,
            "total_concepts_started": len(progress_list),
            "total_concepts_completed": completed,
            "average_mastery": round(avg_mastery, 3),
            "average_confidence": round(avg_confidence, 3),
            "total_attempts": total_attempts,
            "concepts": progress_list,
        }

    except Exception as e:
        logger.exception(f"Error getting progress summary: {e}")
        return {"user_id": user_id, "error": str(e), "total_concepts_started": 0}


def get_concept_progress(concept_id: int) -> Dict:
    """
    Get aggregate progress for a concept across all users (analytics).

    Args:
        concept_id: Concept ID (integer)

    Returns:
        Dict with:
        - concept_id: int
        - total_users: int
        - avg_mastery: float
        - avg_attempts: float
        - users: List[Dict] (per-user progress)
    """
    logger.debug(f"Fetching concept progress: concept={concept_id}")

    try:
        db = get_db()
        progress_list = list(db.progress.find({"concept_id": concept_id}))

        if not progress_list:
            logger.debug(f"No progress found for concept {concept_id}")
            return {
                "concept_id": concept_id,
                "total_users": 0,
                "avg_mastery": 0.0,
                "avg_attempts": 0.0,
                "users": [],
            }

        # Serialize ObjectIds + calculate metrics
        for p in progress_list:
            if "_id" in p:
                p["_id"] = str(p["_id"])

        avg_mastery = sum(p.get("mastery", 0) for p in progress_list) / len(
            progress_list
        )
        avg_attempts = sum(p.get("total_attempts", 0) for p in progress_list) / len(
            progress_list
        )

        logger.info(
            f"Concept progress: concept={concept_id}, users={len(progress_list)}, avg_mastery={avg_mastery:.2f}"
        )

        return {
            "concept_id": concept_id,
            "total_users": len(progress_list),
            "avg_mastery": round(avg_mastery, 3),
            "avg_attempts": round(avg_attempts, 1),
            "users": progress_list,
        }

    except Exception as e:
        logger.exception(f"Error getting concept progress: {e}")
        return {"concept_id": concept_id, "error": str(e), "total_users": 0}


# ==================================================
# MAIN FUNCTION: UPDATE PROGRESS (EMA)
# ==================================================
def update_progress_with_confidence(
    user_id: str, concept_id: int, confidence: float
) -> Dict:
    """
    Update learning progress using EMA (Exponential Moving Average).

    Algorithm:
    - new_mastery = old_mastery * (1 - α) + confidence * α
    - where α is the learning rate (default 0.3)
    - Confidence is expected to be in range [0, 1]

    Also updates:
    - total_attempts (increment by 1)
    - successful_attempts (increment if confidence >= MIN_CONFIDENCE_THRESHOLD)
    - success_rate = successful_attempts / total_attempts
    - status (based on new mastery)
    - last_updated (current timestamp)

    Args:
        user_id: MongoDB ObjectId as string
        concept_id: Concept ID (integer)
        confidence: Confidence score [0, 1]

    Returns:
        Dict with updated progress:
        - user_id: str
        - concept_id: int
        - mastery: float
        - confidence: float
        - total_attempts: int
        - successful_attempts: int
        - success_rate: float
        - status: str
        - last_updated: datetime

    Raises:
        ValueError: If inputs invalid
        Exception: Only on DB errors; logged and graceful
    """
    logger.info(
        f"Updating progress: user={user_id}, concept={concept_id}, confidence={confidence}"
    )

    try:
        # VALIDATE INPUTS
        if not user_id:
            raise ValueError("user_id cannot be empty")

        if concept_id <= 0:
            raise ValueError("concept_id must be positive")

        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be in range [0, 1]")

        db = get_db()

        # FETCH CURRENT PROGRESS (or create if not exists)
        current = db.progress.find_one({"user_id": user_id, "concept_id": concept_id})

        if current:
            # EXISTING PROGRESS: Apply EMA
            old_mastery = current.get("mastery", 0)
            new_mastery = old_mastery * (1 - ALPHA) + confidence * ALPHA
            old_total_attempts = current.get("total_attempts", 0)
            old_successful_attempts = current.get("successful_attempts", 0)

            logger.debug(
                f"EMA update: old_mastery={old_mastery:.3f}, confidence={confidence}, new_mastery={new_mastery:.3f}"
            )
        else:
            # NEW PROGRESS: Initialize
            new_mastery = confidence
            old_total_attempts = 0
            old_successful_attempts = 0
            logger.debug(
                f"New progress record: initializing with confidence={confidence}"
            )

        # UPDATE ATTEMPTS
        new_total_attempts = old_total_attempts + 1

        successful_this_attempt = 1 if confidence >= MIN_CONFIDENCE_THRESHOLD else 0
        new_successful_attempts = old_successful_attempts + successful_this_attempt

        success_rate = (
            new_successful_attempts / new_total_attempts
            if new_total_attempts > 0
            else 0
        )

        # CALCULATE STATUS
        status = _calculate_status(new_mastery)

        # UPDATE IN DB (UPSERT)
        result = db.progress.update_one(
            {"user_id": user_id, "concept_id": concept_id},
            {
                "$set": {
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "mastery": round(new_mastery, 3),
                    "confidence": round(confidence, 3),
                    "total_attempts": new_total_attempts,
                    "successful_attempts": new_successful_attempts,
                    "success_rate": round(success_rate, 3),
                    "status": status,
                    "last_updated": datetime.utcnow(),
                }
            },
            upsert=True,
        )

        logger.info(
            f"Progress updated: user={user_id}, concept={concept_id}, "
            f"mastery={new_mastery:.3f}, status={status}, attempts={new_total_attempts}"
        )

        return {
            "user_id": user_id,
            "concept_id": concept_id,
            "mastery": round(new_mastery, 3),
            "confidence": round(confidence, 3),
            "total_attempts": new_total_attempts,
            "successful_attempts": new_successful_attempts,
            "success_rate": round(success_rate, 3),
            "status": status,
            "last_updated": datetime.utcnow(),
        }

    except ValueError as e:
        logger.warning(f"Validation error updating progress: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error updating progress: {e}")
        raise


# ==================================================
# BATCH OPERATIONS
# ==================================================
def update_progress_batch(updates: list, ignore_errors: bool = True) -> Dict:
    """
    Batch update progress for multiple user-concept pairs.

    Each update should be: {user_id, concept_id, confidence}

    Args:
        updates: List of progress update dicts
        ignore_errors: If True, skip failed updates; if False, stop on first error

    Returns:
        Dict with:
        - success: bool
        - total: int
        - successful: int
        - failed: int
        - errors: List[Dict]
    """
    logger.info(f"Batch updating {len(updates)} progress records")

    successful = 0
    errors = []

    for idx, update in enumerate(updates):
        try:
            update_progress_with_confidence(
                user_id=update.get("user_id"),
                concept_id=update.get("concept_id"),
                confidence=update.get("confidence"),
            )
            successful += 1

        except Exception as e:
            logger.warning(f"Error updating progress [{idx}]: {e}")
            errors.append({"index": idx, "update": update, "error": str(e)})

            if not ignore_errors:
                break

    logger.info(f"Batch update complete: {successful}/{len(updates)} successful")

    return {
        "success": len(errors) == 0,
        "total": len(updates),
        "successful": successful,
        "failed": len(errors),
        "errors": errors,
    }


# ==================================================
# UTILITY: RESET PROGRESS
# ==================================================
def reset_user_progress(user_id: str) -> Dict:
    """
    Reset all progress for a user (admin utility).

    Args:
        user_id: MongoDB ObjectId as string

    Returns:
        Dict with deleted count
    """
    logger.warning(f"Resetting progress for user: {user_id}")

    try:
        db = get_db()
        result = db.progress.delete_many({"user_id": user_id})

        logger.info(f"Progress reset: user={user_id}, deleted={result.deleted_count}")

        return {
            "success": True,
            "user_id": user_id,
            "deleted_count": result.deleted_count,
        }

    except Exception as e:
        logger.exception(f"Error resetting progress: {e}")
        return {"success": False, "error": str(e)}


def reset_concept_progress(concept_id: int) -> Dict:
    """
    Reset all progress for a concept (admin utility).

    Args:
        concept_id: Concept ID (integer)

    Returns:
        Dict with deleted count
    """
    logger.warning(f"Resetting progress for concept: {concept_id}")

    try:
        db = get_db()
        result = db.progress.delete_many({"concept_id": concept_id})

        logger.info(
            f"Concept progress reset: concept={concept_id}, deleted={result.deleted_count}"
        )

        return {
            "success": True,
            "concept_id": concept_id,
            "deleted_count": result.deleted_count,
        }

    except Exception as e:
        logger.exception(f"Error resetting concept progress: {e}")
        return {"success": False, "error": str(e)}
