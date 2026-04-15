"""Repository for persisted adaptive action decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


class AdaptiveActionRepository:
    """Manage adaptive action logs."""

    collection_name = "adaptive_action_logs"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("action_id", 1)], unique=True)
        self.collection.create_index([("user_id", 1), ("path_id", 1), ("created_at", -1)])
        self.collection.create_index([("user_id", 1), ("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("action_type", 1), ("created_at", -1)])

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document["user_id"] = str(document.get("user_id") or "").strip()
        document["path_id"] = str(document.get("path_id") or "").strip() or None
        document["lesson_id"] = str(document.get("lesson_id") or "").strip() or None
        document["target_concepts"] = [
            str(item).strip()
            for item in (document.get("target_concepts") or [])
            if str(item).strip()
        ]
        document["resource_ids"] = [
            str(item).strip()
            for item in (document.get("resource_ids") or [])
            if str(item).strip()
        ]
        document["metadata"] = dict(document.get("metadata") or {})
        document.setdefault("created_at", datetime.utcnow())
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def latest(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        return self.collection.find_one(query, sort=[("created_at", -1)])

    def list_recent(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        return list(
            self.collection.find(query)
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )
