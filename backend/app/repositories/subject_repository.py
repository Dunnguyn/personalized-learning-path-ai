"""MongoDB repository for subjects."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class SubjectRepository:
    """Repository for `subjects` collection."""

    collection_name = "subjects"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("slug", 1)], unique=True, sparse=True)
        self.collection.create_index([("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        return self.collection.find_one({"_id": result.inserted_id}) or {**document, "_id": result.inserted_id}

    def get(self, subject_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(subject_id)})

    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"slug": slug.strip().lower()})

    def list(self) -> List[Dict[str, Any]]:
        return list(self.collection.find().sort("created_at", -1))

    def list_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        q: Optional[str] = None,
        topic: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if q:
            query["$or"] = [
                {"title": {"$regex": q, "$options": "i"}},
                {"slug": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        if topic:
            query["topic"] = {"$regex": topic, "$options": "i"}
        if level:
            query["level"] = level

        total = self.collection.count_documents(query)
        skip = max(page - 1, 0) * size
        items = list(self.collection.find(query).sort("created_at", -1).skip(skip).limit(size))
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size if size else 0,
        }
