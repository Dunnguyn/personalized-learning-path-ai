from datetime import datetime
from backend.app.database.mongo import db


def update_progress(
    user_id: int,
    concept_id: int,
    success: bool
) -> float:
    """
    Update learning progress for a user on a concept.

    Mastery formula:
        mastery = successful_attempts / total_attempts

    Args:
        user_id (int): learner ID
        concept_id (int): concept ID
        success (bool): whether the attempt was successful

    Returns:
        mastery (float): value in range [0.0, 1.0]
    """

    # ---------- 1. Validate ----------
    if user_id <= 0 or concept_id <= 0:
        raise ValueError("user_id and concept_id must be positive integers")

    # ---------- 2. Fetch existing progress ----------
    record = db.progress.find_one(
        {"user_id": user_id, "concept_id": concept_id},
        {"_id": 0}
    )

    prev_total = record.get("total_attempts", 0) if record else 0
    prev_success = record.get("successful_attempts", 0) if record else 0

    # ---------- 3. Update counters ----------
    total_attempts = prev_total + 1
    successful_attempts = prev_success + (1 if success else 0)

    mastery = round(successful_attempts / total_attempts, 2)

    # ---------- 4. Persist ----------
    db.progress.update_one(
        {"user_id": user_id, "concept_id": concept_id},
        {"$set": {
            "user_id": user_id,
            "concept_id": concept_id,
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "mastery": mastery,
            "last_updated": datetime.utcnow()
        }},
        upsert=True
    )

    return mastery
