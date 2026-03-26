"""Evaluation service for experiment tracking and baseline comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.app.database.mongo import get_db
from backend.app.repositories.experiment_repository import ExperimentRepository
from backend.app.repositories.analytics_repository import AnalyticsRepository


class EvaluationService:
    """Experiment and evaluation orchestration."""

    def __init__(
        self, experiment_repo: ExperimentRepository, analytics_repo: AnalyticsRepository
    ):
        self.experiment_repo = experiment_repo
        self.analytics_repo = analytics_repo

    def seed_default_experiments(self) -> None:
        existing = self.experiment_repo.list_experiments(limit=1)
        if existing:
            return

        self.experiment_repo.create_experiment(
            {
                "name": "Learning Path Algorithm Baseline",
                "description": "A/B comparison for recommendation/path strategies",
                "variants": ["rule_based", "semantic_only", "hybrid_adaptive"],
                "start_time": datetime.now(timezone.utc),
                "metrics_summary": {},
                "status": "running",
            }
        )

    def list_experiments(self) -> List[Dict[str, Any]]:
        self.seed_default_experiments()
        experiments = self.experiment_repo.list_experiments(limit=100)
        response = []
        for experiment in experiments:
            item = dict(experiment)
            item.pop("_id", None)
            item["assignment_summary"] = self.experiment_repo.count_assignments(
                item["experiment_id"]
            )
            response.append(item)
        return response

    def get_experiment(self, experiment_id: str) -> Dict[str, Any]:
        self.seed_default_experiments()
        experiment = self.experiment_repo.get_experiment(experiment_id)
        if not experiment:
            raise ValueError("Experiment not found")

        assignment_summary = self.experiment_repo.count_assignments(experiment_id)
        metrics_snapshot = self._build_metrics_snapshot(experiment_id)

        result = dict(experiment)
        result.pop("_id", None)
        result["assignment_summary"] = assignment_summary
        result["metrics_snapshot"] = metrics_snapshot
        return result

    def assign_user_variant(self, experiment_id: str, user_id: str) -> Dict[str, Any]:
        experiment = self.experiment_repo.get_experiment(experiment_id)
        if not experiment:
            raise ValueError("Experiment not found")

        variants = experiment.get("variants") or ["baseline"]
        assignment = self.experiment_repo.assign_user(experiment_id, user_id, variants)
        assignment.pop("_id", None)
        return assignment

    def _build_metrics_snapshot(self, experiment_id: str) -> Dict[str, Any]:
        # Metrics are inferred from event logs tagged with metadata.experiment_id
        event_logs = self.analytics_repo.event_logs
        base_query = {"metadata.experiment_id": experiment_id}

        shown = event_logs.count_documents(
            {**base_query, "event_type": "recommendation_shown"}
        )
        clicked = event_logs.count_documents(
            {**base_query, "event_type": "recommendation_clicked"}
        )
        lp_gen = event_logs.count_documents(
            {**base_query, "event_type": "learning_path_generated"}
        )
        lp_success = event_logs.count_documents(
            {**base_query, "event_type": "learning_path_generated", "success": True}
        )

        return {
            "recommendation_ctr": round((clicked / shown) if shown else 0.0, 4),
            "learning_path_success_rate": round(
                (lp_success / lp_gen) if lp_gen else 0.0, 4
            ),
            "shown": shown,
            "clicked": clicked,
            "learning_path_generated": lp_gen,
        }


db = get_db()
experiment_repository = ExperimentRepository(db)
analytics_repository = AnalyticsRepository(db)
evaluation_service = EvaluationService(experiment_repository, analytics_repository)
