"""Repository for learner state snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


class LearnerStateSnapshotRepository:
    """Manage `learner_state_snapshots` collection."""

    collection_name = "learner_state_snapshots"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("user_id", 1), ("snapshot_time", -1)])
        self.collection.create_index(
            [("user_id", 1), ("is_latest", 1)], partialFilterExpression={"is_latest": True}
        )
        self.collection.create_index([("risk_level", 1), ("snapshot_time", -1)])

    def upsert_latest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        user_id = str(document.get("user_id") or "")
        snapshot_time = document.get("snapshot_time") or datetime.utcnow()
        document["user_id"] = user_id
        document["snapshot_time"] = snapshot_time
        document["is_latest"] = True

        self.collection.update_many({"user_id": user_id, "is_latest": True}, {"$set": {"is_latest": False}})
        self.collection.insert_one(document)
        return self.get_latest(user_id) or document

    def get_latest(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one(
            {"user_id": str(user_id)},
            sort=[("is_latest", -1), ("snapshot_time", -1)],
        )

    def list_recent(self, user_id: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("snapshot_time", -1)
            .limit(max(1, int(limit)))
        )

    def distinct_user_ids(self) -> List[str]:
        return [str(item) for item in self.collection.distinct("user_id") if str(item).strip()]
