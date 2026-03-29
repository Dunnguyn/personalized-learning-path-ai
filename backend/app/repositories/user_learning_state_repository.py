"""Repository for user learning state used by adaptive loop."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class UserLearningStateRepository:
    """Manage adaptive user learning state snapshots."""

    collection_name = "user_learning_state"

    def __init__(self, db) -> None:
        self.collection = db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("user_id", 1), ("subject_id", 1), ("lesson_id", 1)], unique=True
        )
        self.collection.create_index([("user_id", 1), ("updated_at", -1)])

    def get_state(
        self,
        *,
        user_id: str,
        subject_id: str,
        lesson_id: str,
    ) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {
                "user_id": str(user_id),
                "subject_id": str(subject_id),
                "lesson_id": str(lesson_id),
            }
        )

    def upsert_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("updated_at", datetime.utcnow())
        key = {
            "user_id": str(document["user_id"]),
            "subject_id": str(document["subject_id"]),
            "lesson_id": str(document["lesson_id"]),
        }
        self.collection.update_one(key, {"$set": document}, upsert=True)
        return self.collection.find_one(key) or document
