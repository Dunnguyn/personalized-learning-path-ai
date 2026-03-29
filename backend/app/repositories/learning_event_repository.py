"""Repository for adaptive learning events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class LearningEventRepository:
    """Manage `learning_events` collection."""

    collection_name = "learning_events"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("event_id", 1)], unique=True)
        self.collection.create_index([("user_id", 1), ("created_at", -1)])
        self.collection.create_index([("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("resource_id", 1), ("created_at", -1)])
        self.collection.create_index([("event_type", 1), ("created_at", -1)])
        self.collection.create_index([("concept_ids", 1), ("created_at", -1)])

    @staticmethod
    def _normalize_id(value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, ObjectId):
            return str(value)
        return str(value)

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("created_at", datetime.utcnow())
        document["user_id"] = str(document.get("user_id") or "")
        document["resource_id"] = self._normalize_id(document.get("resource_id"))
        document["lesson_id"] = self._normalize_id(document.get("lesson_id"))
        document["path_id"] = self._normalize_id(document.get("path_id"))
        document["concept_ids"] = [
            str(item) for item in document.get("concept_ids", []) if str(item).strip()
        ]
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def latest_for_user(self, user_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )

    def latest_one(
        self,
        user_id: str,
        *,
        lesson_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        if event_type:
            query["event_type"] = str(event_type)
        return self.collection.find_one(query, sort=[("created_at", -1)])

    def list_since(
        self,
        *,
        since: datetime,
        user_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"created_at": {"$gte": since}}
        if user_id:
            query["user_id"] = str(user_id)
        if resource_id:
            query["resource_id"] = str(resource_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        return list(
            self.collection.find(query)
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )

    def distinct_user_ids(self) -> List[str]:
        return [str(item) for item in self.collection.distinct("user_id") if str(item).strip()]
