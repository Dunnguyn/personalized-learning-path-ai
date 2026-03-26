"""Repository for A/B experiments and assignments."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)


class ExperimentRepository:
    """Manage experiments and user variant assignments."""

    def __init__(self, db):
        self.db = db
        self.experiments = db.experiment_runs
        self.assignments = db.ab_test_assignments
        self._create_indexes()

    def _create_indexes(self) -> None:
        try:
            self.experiments.create_index([("experiment_id", 1)], unique=True)
            self.experiments.create_index([("start_time", -1)])
            self.assignments.create_index(
                [("experiment_id", 1), ("user_id", 1)], unique=True
            )
            self.assignments.create_index([("variant", 1), ("assigned_at", -1)])
        except Exception as exc:
            logger.warning("Failed to create experiment indexes: %s", exc)

    def create_experiment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("experiment_id", str(uuid.uuid4()))
        document.setdefault("start_time", datetime.now(timezone.utc))
        document.setdefault("end_time", None)
        document.setdefault("metrics_summary", {})
        document.setdefault("status", "running")
        self.experiments.insert_one(document)
        return document

    def list_experiments(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.experiments.find({}).sort("start_time", -1).limit(limit))

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        return self.experiments.find_one({"experiment_id": experiment_id})

    def assign_user(
        self, experiment_id: str, user_id: str, variants: List[str]
    ) -> Dict[str, Any]:
        existing = self.assignments.find_one(
            {"experiment_id": experiment_id, "user_id": user_id}
        )
        if existing:
            return existing

        stable_hash = hashlib.md5(
            f"{experiment_id}:{user_id}".encode("utf-8")
        ).hexdigest()
        bucket = int(stable_hash[:8], 16)
        variant = variants[bucket % len(variants)]

        assignment = {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant": variant,
            "assigned_at": datetime.now(timezone.utc),
        }
        self.assignments.insert_one(assignment)
        return assignment

    def count_assignments(self, experiment_id: str) -> Dict[str, int]:
        rows = list(
            self.assignments.find({"experiment_id": experiment_id}, {"variant": 1})
        )
        result: Dict[str, int] = {}
        for row in rows:
            variant = str(row.get("variant", "unknown"))
            result[variant] = result.get(variant, 0) + 1
        return result
