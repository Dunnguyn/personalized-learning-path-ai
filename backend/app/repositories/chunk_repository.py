"""MongoDB access for chunk-level resource documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class ResourceChunkRepository:
    """Repository for `resource_chunks` collection."""

    collection_name = "resource_chunks"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("resource_id", 1), ("chunk_index", 1)], unique=True
        )
        self.collection.create_index([("created_at", -1)])
        self.collection.create_index([("metadata.topic", 1), ("metadata.level", 1)])

    def insert_many(self, chunks: List[Dict[str, Any]]) -> int:
        if not chunks:
            return 0
        now = datetime.utcnow()
        normalized = []
        for chunk in chunks:
            doc = dict(chunk)
            doc.setdefault("created_at", now)
            normalized.append(doc)
        result = self.collection.insert_many(normalized, ordered=False)
        return len(result.inserted_ids)

    def count_for_resource(self, resource_id: str | ObjectId) -> int:
        return self.collection.count_documents(
            {"resource_id": self._to_object_id(resource_id)}
        )

    def delete_for_resource(self, resource_id: str | ObjectId) -> int:
        result = self.collection.delete_many(
            {"resource_id": self._to_object_id(resource_id)}
        )
        return result.deleted_count

    def get_by_ids(self, ids: List[str]) -> List[Dict[str, Any]]:
        object_ids = [self._to_object_id(item) for item in ids]
        return list(self.collection.find({"_id": {"$in": object_ids}}))

    def get_by_resource_ids(
        self, resource_ids: List[str | ObjectId]
    ) -> List[Dict[str, Any]]:
        object_ids = [self._to_object_id(item) for item in resource_ids]
        return list(self.collection.find({"resource_id": {"$in": object_ids}}))

    def count_total(self) -> int:
        return self.collection.count_documents({})

    def count_with_embeddings(self) -> int:
        return self.collection.count_documents(
            {"embedding": {"$exists": True, "$type": "array", "$ne": []}}
        )

    def count_without_embeddings(self) -> int:
        return self.collection.count_documents(
            {
                "$or": [
                    {"embedding": {"$exists": False}},
                    {"embedding": []},
                ]
            }
        )

    def count_by_embedding_backend(self) -> Dict[str, int]:
        pipeline = [
            {
                "$group": {
                    "_id": {"$ifNull": ["$metadata.embedding_backend", "missing"]},
                    "count": {"$sum": 1},
                }
            }
        ]
        return {
            str(item.get("_id") or "missing"): int(item.get("count") or 0)
            for item in self.collection.aggregate(pipeline)
        }

    def find_embedding_backfill_candidates(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "$or": [
                {"embedding": {"$exists": False}},
                {"embedding": []},
                {"metadata.embedding_backend": "hash_fallback"},
                {"metadata.embedding_backend": {"$exists": False}},
            ]
        }
        return list(
            self.collection.find(
                query,
                {
                    "_id": 1,
                    "resource_id": 1,
                    "chunk_index": 1,
                    "content": 1,
                    "metadata": 1,
                },
            ).limit(limit)
        )

    def update_embedding(
        self,
        chunk_id: str | ObjectId,
        *,
        embedding: List[float],
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        updates: Dict[str, Any] = {
            "embedding": list(embedding),
            "updated_at": datetime.utcnow(),
        }
        for key, value in (metadata_updates or {}).items():
            updates[f"metadata.{key}"] = value
        self.collection.update_one(
            {"_id": self._to_object_id(chunk_id)},
            {"$set": updates},
        )

    def candidate_chunks(
        self,
        *,
        topic: Optional[str] = None,
        level: Optional[str] = None,
        resource_ids: Optional[List[str | ObjectId]] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"embedding": {"$exists": True}}
        if topic:
            query["metadata.topic"] = topic
        if level:
            query["metadata.level"] = level
        if resource_ids:
            query["resource_id"] = {
                "$in": [self._to_object_id(item) for item in resource_ids]
            }
        return list(
            self.collection.find(
                query,
                {
                    "_id": 1,
                    "resource_id": 1,
                    "chunk_index": 1,
                    "content": 1,
                    "embedding": 1,
                    "metadata": 1,
                },
            )
            .sort([("created_at", -1), ("_id", -1)])
            .limit(limit)
        )
