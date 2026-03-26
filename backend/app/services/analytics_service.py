"""Analytics service for learner/admin/system dashboards."""

from __future__ import annotations

from typing import Any, Dict

from backend.app.database.mongo import get_db
from backend.app.repositories.analytics_repository import AnalyticsRepository


class AnalyticsService:
    """Compose dashboard analytics from multiple repositories/collections."""

    def __init__(self, repository: AnalyticsRepository):
        self.repository = repository

    def get_learner_dashboard(self, user_id: str) -> Dict[str, Any]:
        completion = self.repository.learner_completion_stats(user_id)
        gain = self.repository.learner_mastery_confidence_gain(user_id)
        time_streak = self.repository.learner_time_and_streak(user_id)
        recommendation = self.repository.learner_recommendation_and_quiz_stats(user_id)

        return {
            "user_id": user_id,
            "completion": completion,
            "gain": gain,
            "time_and_streak": time_streak,
            "recommendation_and_quiz": recommendation,
        }

    def get_admin_overview(self) -> Dict[str, Any]:
        return self.repository.admin_overview()

    def get_admin_retention(self) -> Dict[str, Any]:
        return self.repository.retention_overview()

    def get_admin_recommendation(self) -> Dict[str, Any]:
        return self.repository.recommendation_overview()

    def get_system_performance(self) -> Dict[str, Any]:
        return self.repository.system_performance_overview()


db = get_db()
analytics_repository = AnalyticsRepository(db)
analytics_service = AnalyticsService(analytics_repository)
