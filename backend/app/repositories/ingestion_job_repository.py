"""MongoDB access for background ingestion jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class IngestionJobRepository:
    """Repository for `ingestion_jobs` collection."""

    collection_name = "ingestion_jobs"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("resource_id", 1), ("created_at", -1)])
        self.collection.create_index([("status", 1), ("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("status", "pending")
        document.setdefault("chunks_count", 0)
        document.setdefault("processing_time", 0.0)
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        created = self.collection.find_one({"_id": result.inserted_id})
        return created or {**document, "_id": result.inserted_id}

    def update(
        self, job_id: str | ObjectId, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        updates = {**updates, "updated_at": datetime.utcnow()}
        self.collection.update_one(
            {"_id": self._to_object_id(job_id)}, {"$set": updates}
        )
        return self.get(job_id)

    def get(self, job_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(job_id)})
