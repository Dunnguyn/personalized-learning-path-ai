"""MongoDB access for top-level learning resources."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class ResourceRepository:
    """Repository for `resources` collection."""

    collection_name = "resources"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("created_at", -1)])
        self.collection.create_index([("type", 1), ("topic", 1)])
        self.collection.create_index([("source", 1), ("created_at", -1)])
        self.collection.create_index([("status", 1), ("created_at", -1)])
        self.collection.create_index(
            [("metadata.content_hash", 1)],
            sparse=True,
            name="resource_content_hash_idx",
        )
        self.collection.create_index(
            [("metadata.file_hash", 1)],
            sparse=True,
            name="resource_file_hash_idx",
        )
        self.collection.create_index(
            [("metadata.video_id", 1)],
            sparse=True,
            name="resource_video_id_idx",
        )

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        document.setdefault("status", "pending")
        document.setdefault("chunks_count", 0)
        document.setdefault("processing_time", 0.0)
        result = self.collection.insert_one(document)
        created = self.collection.find_one({"_id": result.inserted_id})
        return created or {**document, "_id": result.inserted_id}

    def update(
        self,
        resource_id: str | ObjectId,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        updates = {**updates, "updated_at": datetime.utcnow()}
        self.collection.update_one(
            {"_id": self._to_object_id(resource_id)},
            {"$set": updates},
        )
        return self.get(resource_id)

    def get(self, resource_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(resource_id)})

    def get_many(self, resource_ids: List[str | ObjectId]) -> List[Dict[str, Any]]:
        object_ids = [self._to_object_id(item) for item in resource_ids]
        return list(self.collection.find({"_id": {"$in": object_ids}}))

    def delete(self, resource_id: str | ObjectId) -> int:
        result = self.collection.delete_one({"_id": self._to_object_id(resource_id)})
        return result.deleted_count

    def find_duplicate(
        self,
        *,
        content_hash: Optional[str] = None,
        file_hash: Optional[str] = None,
        video_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query_clauses: List[Dict[str, Any]] = []
        if content_hash:
            query_clauses.append({"metadata.content_hash": content_hash})
        if file_hash:
            query_clauses.append({"metadata.file_hash": file_hash})
        if video_id:
            query_clauses.append({"metadata.video_id": video_id})
        if not query_clauses:
            return None
        return self.collection.find_one({"$or": query_clauses})

    def list(
        self,
        *,
        page: int = 1,
        size: int = 10,
        topic: Optional[str] = None,
        level: Optional[str] = None,
        source: Optional[str] = None,
        resource_type: Optional[str] = None,
        concept_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if topic:
            query["topic"] = {"$regex": topic, "$options": "i"}
        if level:
            query["metadata.level"] = level
        if source:
            query["source"] = source
        if resource_type:
            query["type"] = resource_type
        if concept_id is not None:
            query["metadata.concept_id"] = concept_id

        total = self.collection.count_documents(query)
        skip = max(page - 1, 0) * size
        documents = list(
            self.collection.find(query).sort("created_at", -1).skip(skip).limit(size)
        )
        return {
            "items": documents,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size if size else 0,
        }

    def find_latest_duplicate_groups(self) -> List[Dict[str, Any]]:
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"metadata.content_hash": {"$exists": True, "$ne": None}},
                        {"metadata.file_hash": {"$exists": True, "$ne": None}},
                        {"metadata.video_id": {"$exists": True, "$ne": None}},
                    ]
                }
            },
            {
                "$project": {
                    "dedupe_key": {
                        "$ifNull": [
                            "$metadata.video_id",
                            {
                                "$ifNull": [
                                    "$metadata.file_hash",
                                    "$metadata.content_hash",
                                ]
                            },
                        ]
                    },
                    "created_at": 1,
                }
            },
            {
                "$group": {
                    "_id": "$dedupe_key",
                    "count": {"$sum": 1},
                    "resources": {
                        "$push": {
                            "_id": "$_id",
                            "created_at": "$created_at",
                        }
                    },
                }
            },
            {"$match": {"count": {"$gt": 1}, "_id": {"$ne": None}}},
        ]
        return list(self.collection.aggregate(pipeline))

    def delete_many(self, resource_ids: List[ObjectId]) -> int:
        if not resource_ids:
            return 0
        result = self.collection.delete_many({"_id": {"$in": resource_ids}})
        return result.deleted_count
