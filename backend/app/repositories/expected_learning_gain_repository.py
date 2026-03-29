"""Repository for expected learning gain statistics."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


class ExpectedLearningGainRepository:
    """Manage `expected_learning_gain_stats` collection."""

    collection_name = "expected_learning_gain_stats"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("resource_id", 1), ("concept_id", 1)], unique=True)
        self.collection.create_index([("computed_at", -1)])
        self.collection.create_index([("concept_id", 1), ("computed_at", -1)])

    def upsert_stat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("computed_at", datetime.utcnow())
        key = {
            "resource_id": str(document.get("resource_id") or ""),
            "concept_id": str(document.get("concept_id") or "general"),
        }
        self.collection.update_one(key, {"$set": document}, upsert=True)
        return self.collection.find_one(key) or document

    def get_stat(self, *, resource_id: str, concept_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {"resource_id": str(resource_id)}
        if concept_id:
            query["concept_id"] = str(concept_id)
            exact = self.collection.find_one(query)
            if exact:
                return exact
        return self.collection.find_one(
            {"resource_id": str(resource_id)},
            sort=[("sample_size", -1), ("computed_at", -1)],
        )

    def list_by_resource_ids(self, resource_ids: List[str]) -> List[Dict[str, Any]]:
        normalized = [str(item) for item in resource_ids if str(item).strip()]
        if not normalized:
            return []
        return list(self.collection.find({"resource_id": {"$in": normalized}}))
