"""Repository for learner feedback and normalized learner signals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from backend.app.database.mongo import get_db


class LearnerSignalRepository:
    """MongoDB repository for feedback and signal collections."""

    def __init__(self) -> None:
        self.db = get_db()
        self.feedback_collection = self.db.learner_feedback
        self.signal_collection = self.db.learner_signals
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        try:
            self.feedback_collection.create_index([("user_id", 1), ("created_at", -1)])
            self.feedback_collection.create_index(
                [("path_id", 1), ("lesson_id", 1), ("created_at", -1)]
            )
            self.signal_collection.create_index([("user_id", 1), ("created_at", -1)])
            self.signal_collection.create_index(
                [("signal_type", 1), ("created_at", -1)]
            )
            self.signal_collection.create_index(
                [("path_id", 1), ("lesson_id", 1), ("created_at", -1)]
            )
        except Exception:
            pass

    def create_feedback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document = dict(payload)
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.feedback_collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def create_signal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document = dict(payload)
        document.setdefault("created_at", now)
        result = self.signal_collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def list_feedback(self, *, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return list(
            self.feedback_collection.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(max(1, limit))
        )

    def list_signals(self, *, user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        return list(
            self.signal_collection.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(max(1, limit))
        )
