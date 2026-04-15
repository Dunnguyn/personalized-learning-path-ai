"""Repository for learner state snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


class LearnerStateSnapshotRepository:
    """Manage learner state snapshots by user and path."""

    collection_name = "learner_state_snapshots"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("snapshot_id", 1)], unique=True, sparse=True)
        self.collection.create_index([("user_id", 1), ("path_id", 1), ("updated_at", -1)])
        self.collection.create_index([("user_id", 1), ("snapshot_time", -1)])
        self.collection.create_index(
            [("user_id", 1), ("path_id", 1), ("is_latest", 1)],
            partialFilterExpression={"is_latest": True},
        )
        self.collection.create_index([("risk_level", 1), ("updated_at", -1)])

    def upsert_latest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        user_id = str(document.get("user_id") or "").strip()
        path_id = str(document.get("path_id") or "").strip() or None
        updated_at = document.get("updated_at") or document.get("snapshot_time") or datetime.utcnow()
        document["user_id"] = user_id
        document["path_id"] = path_id
        document["updated_at"] = updated_at
        document["snapshot_time"] = document.get("snapshot_time") or updated_at
        document["is_latest"] = True

        latest_query: Dict[str, Any] = {"user_id": user_id, "is_latest": True}
        if path_id:
            latest_query["path_id"] = path_id

        self.collection.update_many(latest_query, {"$set": {"is_latest": False}})
        self.collection.insert_one(document)
        return self.get_latest(user_id=user_id, path_id=path_id) or document

    def get_latest(
        self,
        user_id: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["current_lesson_id"] = str(lesson_id)
        return self.collection.find_one(
            query,
            sort=[("is_latest", -1), ("updated_at", -1), ("snapshot_time", -1)],
        )

    def list_recent(
        self,
        user_id: str,
        *,
        path_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        return list(
            self.collection.find(query)
            .sort([("updated_at", -1), ("snapshot_time", -1)])
            .limit(max(1, int(limit)))
        )

    def distinct_user_ids(self) -> List[str]:
        return [str(item) for item in self.collection.distinct("user_id") if str(item).strip()]
