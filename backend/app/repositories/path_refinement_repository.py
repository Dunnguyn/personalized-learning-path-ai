"""Repository for path refinement actions and intervention logs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from backend.app.database.mongo import get_db


class PathRefinementRepository:
    """MongoDB repository for refinement and intervention tracking."""

    def __init__(self) -> None:
        self.db = get_db()
        self.refinement_actions = self.db.path_refinement_actions
        self.intervention_logs = self.db.intervention_logs
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        try:
            self.refinement_actions.create_index([("action_id", 1)], unique=True)
            self.refinement_actions.create_index([("user_id", 1), ("created_at", -1)])
            self.refinement_actions.create_index([("path_id", 1), ("created_at", -1)])
            self.refinement_actions.create_index([("lesson_id", 1), ("created_at", -1)])
            self.intervention_logs.create_index([("user_id", 1), ("created_at", -1)])
            self.intervention_logs.create_index(
                [("path_id", 1), ("lesson_id", 1), ("created_at", -1)]
            )
            self.intervention_logs.create_index(
                [("intervention_type", 1), ("created_at", -1)]
            )
        except Exception:
            pass

    def create_refinement_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document = dict(payload)
        document.setdefault("created_at", now)
        document.setdefault("outcome_status", "pending")
        result = self.refinement_actions.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def create_intervention_log(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document = dict(payload)
        document.setdefault("created_at", now)
        result = self.intervention_logs.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def list_refinements(
        self,
        *,
        user_id: str,
        limit: int = 100,
        path_id: str | None = None,
        lesson_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        return list(
            self.refinement_actions.find(query)
            .sort("created_at", -1)
            .limit(max(1, limit))
        )

    def list_interventions(
        self,
        *,
        user_id: str,
        limit: int = 100,
        path_id: str | None = None,
        lesson_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if path_id:
            query["path_id"] = str(path_id)
        if lesson_id:
            query["lesson_id"] = str(lesson_id)
        return list(
            self.intervention_logs.find(query)
            .sort("created_at", -1)
            .limit(max(1, limit))
        )
