"""Repository for adaptive decision/audit events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


class AdaptiveEventRepository:
    """Store adaptive loop events for analytics and audit."""

    collection_name = "adaptive_events"

    def __init__(self, db) -> None:
        self.collection = db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("event_id", 1)], unique=True)
        self.collection.create_index([("user_id", 1), ("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("decision", 1), ("created_at", -1)])

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("created_at", datetime.utcnow())
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def list_by_user(self, *, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )
