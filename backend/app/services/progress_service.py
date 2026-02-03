from datetime import datetime
from backend.app.database.mongo import db

ALPHA = 0.3  # learning rate cho EMA


def update_progress_with_confidence(
    user_id: int,
    concept_id: int,
    confidence: float
) -> float:
    """
    Update learning progress using confidence-based EMA.

    Formula:
        new_mastery = old_mastery * (1 - α) + confidence * α

    Args:
        user_id (int): learner ID
        concept_id (int): concept ID
        confidence (float): AI-evaluated confidence [0.0 - 1.0]

    Returns:
        mastery (float): updated mastery score
    """

    # ---------- 1. Validate ----------
    if user_id <= 0 or concept_id <= 0:
        raise ValueError("user_id and concept_id must be positive integers")

    confidence = max(0.0, min(confidence, 1.0))

    # ---------- 2. Fetch existing progress ----------
    record = db.progress.find_one(
        {"user_id": user_id, "concept_id": concept_id},
        {"_id": 0}
    )

    old_mastery = record.get("mastery", 0.0) if record else 0.0
    total_attempts = (record.get("total_attempts", 0) if record else 0) + 1

    # ---------- 3. EMA update ----------
    new_mastery = round(
        old_mastery * (1 - ALPHA) + confidence * ALPHA,
        2
    )

    # ---------- 4. Persist ----------
    db.progress.update_one(
        {"user_id": user_id, "concept_id": concept_id},
        {"$set": {
            "user_id": user_id,
            "concept_id": concept_id,
            "mastery": new_mastery,
            "total_attempts": total_attempts,
            "last_updated": datetime.utcnow()
        }},
        upsert=True
    )

    return new_mastery
