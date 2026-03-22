"""MongoDB repository for chapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class ChapterRepository:
    """Repository for `chapters` collection."""

    collection_name = "chapters"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("subject_id", 1), ("order", 1)])
        self.collection.create_index([("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        return self.collection.find_one({"_id": result.inserted_id}) or {**document, "_id": result.inserted_id}

    def get(self, chapter_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(chapter_id)})

    def list_by_subject(self, subject_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"subject_id": self._to_object_id(subject_id)}).sort("order", 1)
        )
