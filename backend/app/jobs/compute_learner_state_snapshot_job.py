"""Batch job to precompute learner state snapshots."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db
from backend.app.services.adaptive_learning_loop_service import (
    adaptive_learning_loop_service,
)


class ComputeLearnerStateSnapshotJob:
    """Refresh learner state snapshots for one or many users."""

    def __init__(self) -> None:
        self.db = get_db()

    def _candidate_user_ids(self) -> List[str]:
        user_ids = set(
            str(item)
            for item in self.db.users.distinct("_id")
            if str(item).strip()
        )
        user_ids.update(adaptive_learning_loop_service.learning_event_repository.distinct_user_ids())
        user_ids.update(adaptive_learning_loop_service.snapshot_repository.distinct_user_ids())
        return sorted(user_ids)

    def run(
        self,
        *,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        user_ids = [str(user_id)] if user_id else self._candidate_user_ids()
        processed = 0
        snapshots: List[Dict[str, Any]] = []
        for current_user_id in user_ids:
            processed += 1
            snapshot = adaptive_learning_loop_service.update_learner_state(
                user_id=current_user_id,
                persist=not dry_run,
            )
            snapshots.append(snapshot)
        return {
            "job": "learner_state",
            "processed": processed,
            "written": 0 if dry_run else processed,
            "dry_run": dry_run,
            "items": snapshots[:5],
        }


compute_learner_state_snapshot_job = ComputeLearnerStateSnapshotJob()
