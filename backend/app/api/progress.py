from fastapi import APIRouter
from datetime import datetime
from backend.app.database.mongo import db

router = APIRouter()

@router.post("/update")
def update_progress(user_id: int, concept_id: int, success: bool):
    record = db.progress.find_one({
        "user_id": user_id,
        "concept_id": concept_id
    })

    total = (record["total_attempts"] if record else 0) + 1
    success_cnt = (record["successful_attempts"] if record else 0) + (1 if success else 0)
    mastery = round(success_cnt / total, 2)

    db.progress.update_one(
        {"user_id": user_id, "concept_id": concept_id},
        {"$set": {
            "total_attempts": total,
            "successful_attempts": success_cnt,
            "mastery": mastery,
            "last_updated": datetime.utcnow()
        }},
        upsert=True
    )

    return {"mastery": mastery}
