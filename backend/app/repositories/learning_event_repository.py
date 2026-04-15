"""Repository for adaptive learning loop events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class LearningEventRepository:
    """Manage persisted learner interaction events."""

    collection_name = "learning_events"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("event_id", 1)], unique=True)
        self.collection.create_index([("user_id", 1), ("path_id", 1), ("created_at", -1)])
        self.collection.create_index([("user_id", 1), ("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("path_id", 1), ("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("resource_id", 1), ("created_at", -1)])
        self.collection.create_index([("question_id", 1), ("created_at", -1)])
        self.collection.create_index([("event_type", 1), ("created_at", -1)])
        self.collection.create_index([("concept_ids", 1), ("created_at", -1)])

    @staticmethod
    def _normalize_id(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        if isinstance(value, ObjectId):
            return str(value)
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _normalize_payload(value: Any) -> Dict[str, Any]:
        return dict(value or {}) if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_string_list(values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        return [str(item).strip() for item in values if str(item).strip()]

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        normalized_payload = self._normalize_payload(
            document.get("payload") or document.get("metadata")
        )
        document.setdefault("created_at", datetime.utcnow())
        document["user_id"] = str(document.get("user_id") or "").strip()
        document["path_id"] = self._normalize_id(document.get("path_id"))
        document["lesson_id"] = self._normalize_id(document.get("lesson_id"))
        document["resource_id"] = self._normalize_id(document.get("resource_id"))
        document["question_id"] = self._normalize_id(document.get("question_id"))
        document["concept_ids"] = self._normalize_string_list(document.get("concept_ids"))
        document["payload"] = normalized_payload
        document["metadata"] = dict(normalized_payload)
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible alias."""
        return self.create(payload)

    def latest_for_user(self, user_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        return self.list_recent(user_id=user_id, limit=limit)

    def list_recent(
        self,
        *,
        user_id: Optional[str] = None,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if user_id:
            query["user_id"] = str(user_id)
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        if resource_id:
            query["resource_id"] = str(resource_id)
        if event_type:
            query["event_type"] = str(event_type)
        return list(
            self.collection.find(query)
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )

    def latest_one(
        self,
        user_id: str,
        *,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
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
        path_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"created_at": {"$gte": since}}
        if user_id:
            query["user_id"] = str(user_id)
        if path_id:
            query["path_id"] = str(path_id)
        if resource_id:
            query["resource_id"] = str(resource_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        if event_type:
            query["event_type"] = str(event_type)
        return list(
            self.collection.find(query)
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )

    def distinct_user_ids(self) -> List[str]:
        return [str(item) for item in self.collection.distinct("user_id") if str(item).strip()]
