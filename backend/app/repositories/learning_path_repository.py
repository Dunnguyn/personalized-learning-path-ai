"""MongoDB repository for generated learning paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.app.database.mongo import get_db


class LearningPathRepository:
    """Repository for `learning_paths` collection."""

    collection_name = "learning_paths"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("path_id", 1)], unique=True)
        self.collection.create_index([("user_id", 1), ("created_at", -1)])
        self.collection.create_index([("subject_id", 1), ("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        created = self.collection.find_one({"_id": result.inserted_id})
        return created or {**document, "_id": result.inserted_id}

    def get_by_path_id(self, path_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"path_id": path_id})

    def delete_by_path_id(self, path_id: str, *, user_id: Optional[str] = None) -> int:
        query: Dict[str, Any] = {"path_id": path_id}
        if user_id is not None:
            query["user_id"] = user_id
        result = self.collection.delete_one(query)
        return result.deleted_count
