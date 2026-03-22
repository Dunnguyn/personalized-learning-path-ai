"""MongoDB repository for lessons."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class LessonRepository:
    """Repository for `lessons` collection."""

    collection_name = "lessons"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("chapter_id", 1), ("order", 1)])
        self.collection.create_index([("subject_id", 1), ("chapter_id", 1)])
        self.collection.create_index([("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        return self.collection.find_one({"_id": result.inserted_id}) or {**document, "_id": result.inserted_id}

    def get(self, lesson_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(lesson_id)})

    def update(self, lesson_id: str | ObjectId, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.collection.update_one(
            {"_id": self._to_object_id(lesson_id)},
            {"$set": {**updates, "updated_at": datetime.utcnow()}},
        )
        return self.get(lesson_id)

    def list_by_chapter(self, chapter_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"chapter_id": self._to_object_id(chapter_id)}).sort("order", 1)
        )
