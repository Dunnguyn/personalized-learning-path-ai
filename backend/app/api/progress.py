from datetime import datetime
from typing import Dict
from backend.app.database.mongo import get_db


# ===== 1. UPDATE PROGRESS =====
def update_progress(
    user_id: str,
    concept: str,
    success: bool
) -> Dict:
    db = get_db()

    record = db.progress.find_one({
        "user_id": user_id,
        "concept": concept
    })

    if record:
        total = record.get("total_attempts", 0) + 1
        successful = record.get("successful_attempts", 0) + (1 if success else 0)
    else:
        total = 1
        successful = 1 if success else 0

    mastery = min(1.0, round(successful / total, 2))

    db.progress.update_one(
        {"user_id": user_id, "concept": concept},
        {
            "$set": {
                "total_attempts": total,
                "successful_attempts": successful,
                "mastery": mastery,
                "last_updated": datetime.utcnow()
            }
        },
        upsert=True
    )

    return {
        "user_id": user_id,
        "concept": concept,
        "mastery": mastery
    }


# ===== 2. GET USER MASTERY MAP =====
def get_user_mastery(user_id: str) -> Dict[str, float]:
    db = get_db()
    progress = db.progress.find({"user_id": user_id})
    return {
        p["concept"]: p.get("mastery", 0.0)
        for p in progress
    }
