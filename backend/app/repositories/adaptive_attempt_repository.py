"""Repository for adaptive lesson quiz attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


class AdaptiveAttemptRepository:
    """Persist and query adaptive quiz attempts."""

    collection_name = "lesson_quiz_attempts"

    def __init__(self, db) -> None:
        self.collection = db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("user_id", 1), ("lesson_id", 1), ("submitted_at", -1)])
        self.collection.create_index([("attempt_id", 1)], unique=True)
        self.collection.create_index([("path_id", 1), ("lesson_id", 1), ("submitted_at", -1)])

    def create_attempt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("submitted_at", datetime.utcnow())
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def list_attempts(
        self,
        *,
        user_id: str,
        lesson_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find(
                {"user_id": str(user_id), "lesson_id": str(lesson_id)}
            )
            .sort("submitted_at", -1)
            .limit(max(1, int(limit)))
        )

    def latest_attempt(self, *, user_id: str, lesson_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {"user_id": str(user_id), "lesson_id": str(lesson_id)},
            sort=[("submitted_at", -1)],
        )

    def get_recent_attempts(
        self,
        *,
        user_id: str,
        lesson_id: str,
        k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Return the most recent k attempts in descending time order."""
        return list(
            self.collection.find(
                {
                    "user_id": str(user_id),
                    "lesson_id": str(lesson_id),
                }
            )
            .sort("submitted_at", -1)
            .limit(max(1, int(k)))
        )
