from __future__ import annotations

import unittest
from unittest.mock import patch
import sys
import types
import importlib.metadata as importlib_metadata
import pydantic.networks

from fastapi.testclient import TestClient

if "passlib.context" not in sys.modules:
    passlib_module = types.ModuleType("passlib")
    context_module = types.ModuleType("passlib.context")

    class CryptContext:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def verify(self, *_args, **_kwargs):
            return True

        def hash(self, value):
            return str(value)

    context_module.CryptContext = CryptContext
    sys.modules["passlib"] = passlib_module
    sys.modules["passlib.context"] = context_module

if "email_validator" not in sys.modules:
    email_validator_module = types.ModuleType("email_validator")

    class EmailNotValidError(ValueError):
        pass

    def validate_email(value, *args, **kwargs):  # pragma: no cover - import shim only
        del args, kwargs
        return type("ValidatedEmail", (), {"email": value})()

    email_validator_module.EmailNotValidError = EmailNotValidError
    email_validator_module.validate_email = validate_email
    sys.modules["email_validator"] = email_validator_module

_original_metadata_version = importlib_metadata.version


def _patched_metadata_version(distribution_name: str):  # pragma: no cover - import shim only
    if distribution_name == "email-validator":
        return "2.0.0"
    return _original_metadata_version(distribution_name)


importlib_metadata.version = _patched_metadata_version
pydantic.networks.import_email_validator = lambda: None

from backend.app.api.auth import get_current_user
from backend.app.jobs.compute_expected_learning_gain_job import (
    ComputeExpectedLearningGainJob,
)
from backend.app.jobs.compute_learner_state_snapshot_job import (
    ComputeLearnerStateSnapshotJob,
)
from backend.app.jobs.compute_resource_quality_job import ComputeResourceQualityJob
from backend.app.services.adaptive_learning_loop_service import (
    AdaptiveLearningLoopService,
)
from backend.main import app


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.upserts = []

    def find(self, *_args, **_kwargs):
        return self

    def update_one(self, query, update, upsert=False):
        self.upserts.append((query, update, upsert))

    def sort(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self.rows)


class AdaptiveLearningLoopServiceTests(unittest.TestCase):
    def _build_service(self) -> AdaptiveLearningLoopService:
        service = AdaptiveLearningLoopService.__new__(AdaptiveLearningLoopService)
        service._ACTION_TO_MODE = AdaptiveLearningLoopService._ACTION_TO_MODE
        service._safe_float = AdaptiveLearningLoopService._safe_float
        service._average = AdaptiveLearningLoopService._average
        service._lesson_mastery_average = lambda **kwargs: kwargs.get("fallback_average", 0.0)
        service._prerequisite_satisfaction = lambda *_args, **_kwargs: 1.0
        service._resolve_lesson_context = lambda **_kwargs: None
        service.learning_event_repository = type(
            "LearningEventRepoStub",
            (),
            {"latest_one": staticmethod(lambda *_args, **_kwargs: None)},
        )()
        service.snapshot_repository = type(
            "SnapshotRepoStub",
            (),
            {"get_latest": staticmethod(lambda *_args, **_kwargs: None)},
        )()
        service.update_learner_state = lambda **_kwargs: {}
        return service

    def test_fail_quiz_returns_retry_with_easier_resource(self):
        service = self._build_service()
        result = service.decide_next_best_action(
            user_id="user-1",
            learner_snapshot={
                "mastery_by_concept": {"loops": 0.3},
                "confidence_by_concept": {"loops": 0.3},
                "frustration_score": 0.2,
                "quiz_fail_streak": 0,
                "unfinished_resources": 0,
                "resource_abandonment_rate": 0.0,
                "preferred_format": "text",
                "current_focus_concepts": ["loops"],
                "last_quiz_score": 0.2,
            },
            latest_event={"event_type": "quiz_submitted", "metadata": {"score": 0.3}},
        )
        self.assertEqual(result["next_best_action"], "retry_with_easier_resource")

    def test_high_frustration_returns_quick_review(self):
        service = self._build_service()
        result = service.decide_next_best_action(
            user_id="user-2",
            learner_snapshot={
                "mastery_by_concept": {"loops": 0.45},
                "confidence_by_concept": {"loops": 0.41},
                "frustration_score": 0.83,
                "quiz_fail_streak": 1,
                "unfinished_resources": 1,
                "resource_abandonment_rate": 0.2,
                "preferred_format": "text",
                "current_focus_concepts": ["loops"],
            },
            latest_event={"event_type": "resource_abandoned", "metadata": {}},
        )
        self.assertEqual(result["next_best_action"], "quick_review_session")

    def test_lesson_completed_with_high_mastery_moves_to_next_lesson(self):
        service = self._build_service()
        service._resolve_lesson_context = lambda **_kwargs: {"_id": "lesson-1"}
        service._lesson_mastery_average = lambda **_kwargs: 0.82
        result = service.decide_next_best_action(
            user_id="user-3",
            learner_snapshot={
                "mastery_by_concept": {"loops": 0.8},
                "confidence_by_concept": {"loops": 0.75},
                "frustration_score": 0.18,
                "quiz_fail_streak": 0,
                "unfinished_resources": 0,
                "resource_abandonment_rate": 0.0,
                "preferred_format": "text",
                "current_focus_concepts": ["loops"],
                "avg_mastery": 0.8,
            },
            latest_event={"event_type": "lesson_completed", "metadata": {}},
            lesson_id="lesson-1",
        )
        self.assertEqual(result["next_best_action"], "move_to_next_lesson")


class BatchJobTests(unittest.TestCase):
    def test_quality_job_returns_expected_shape(self):
        job = ComputeResourceQualityJob.__new__(ComputeResourceQualityJob)
        job.resources = FakeCollection([{"_id": "r1", "title": "Loops 101"}])
        job.quality_stats = FakeCollection()

        with patch(
            "backend.app.jobs.compute_resource_quality_job.resource_quality_service.get_resource_quality",
            return_value={"resource_id": "r1", "quality_score": 0.72, "sample_size": 3},
        ):
            result = job.run(full=True)

        self.assertEqual(result["job"], "quality")
        self.assertEqual(result["processed"], 1)
        self.assertIn("quality_score", result["items"][0])

    def test_learner_snapshot_job_handles_missing_data(self):
        job = ComputeLearnerStateSnapshotJob.__new__(ComputeLearnerStateSnapshotJob)
        job.db = type("DbStub", (), {"users": type("UsersStub", (), {"distinct": staticmethod(lambda *_: [])})()})()

        with patch(
            "backend.app.jobs.compute_learner_state_snapshot_job.adaptive_learning_loop_service.learning_event_repository.distinct_user_ids",
            return_value=["user-1"],
        ), patch(
            "backend.app.jobs.compute_learner_state_snapshot_job.adaptive_learning_loop_service.snapshot_repository.distinct_user_ids",
            return_value=[],
        ), patch(
            "backend.app.jobs.compute_learner_state_snapshot_job.adaptive_learning_loop_service.update_learner_state",
            return_value={"user_id": "user-1", "risk_level": "low"},
        ):
            result = job.run(dry_run=True)

        self.assertEqual(result["job"], "learner_state")
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["written"], 0)

    def test_expected_gain_job_has_heuristic_fallback(self):
        job = ComputeExpectedLearningGainJob.__new__(ComputeExpectedLearningGainJob)
        job.repository = type(
            "ExpectedGainRepoStub",
            (),
            {"upsert_stat": staticmethod(lambda payload: payload)},
        )()
        job.resource_quality_stats = FakeCollection(
            [{"resource_id": "r1", "quality_score": 0.81}]
        )
        job.learning_events = FakeCollection([])
        job.resources = FakeCollection([])

        result = job.run(resource_id="r1", incremental=False, dry_run=True)

        self.assertEqual(result["job"], "expected_gain")
        self.assertEqual(result["processed"], 1)
        self.assertIn("avg_mastery_gain", result["items"][0])


class AdaptiveApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_current_user] = lambda: {
            "_id": "507f1f77bcf86cd799439011",
            "user_id": "507f1f77bcf86cd799439011",
            "role": "learner",
        }
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_post_adaptive_event(self):
        with patch(
            "backend.app.api.adaptive.adaptive_learning_loop_service.ingest_learning_event",
            return_value={
                "event_id": "evt-1",
                "user_id": "507f1f77bcf86cd799439011",
                "event_type": "quiz_submitted",
                "resource_id": None,
                "lesson_id": "lesson-1",
                "path_id": None,
                "concept_ids": ["loops"],
                "metadata": {"score": 0.3},
                "created_at": "2026-03-29T00:00:00",
            },
        ):
            response = self.client.post(
                "/api/adaptive/events",
                json={
                    "event_type": "quiz_submitted",
                    "lesson_id": "lesson-1",
                    "concept_ids": ["loops"],
                    "metadata": {"score": 0.3},
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["event_type"], "quiz_submitted")

    def test_get_next_action(self):
        with patch(
            "backend.app.api.adaptive.adaptive_learning_loop_service.snapshot_repository.get_latest",
            return_value={"user_id": "507f1f77bcf86cd799439011"},
        ), patch(
            "backend.app.api.adaptive.adaptive_learning_loop_service.decide_next_best_action",
            return_value={
                "user_id": "507f1f77bcf86cd799439011",
                "next_best_action": "study_worked_example",
                "reason": "Need an example before retrying.",
                "priority": "high",
                "recommended_mode": "reinforce_weaknesses",
                "target_concepts": ["loops"],
                "lesson_id": "lesson-1",
                "resource_id": None,
                "estimated_total_time": 12,
            },
        ):
            response = self.client.get("/api/adaptive/next-action?lesson_id=lesson-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next_best_action"], "study_worked_example")

    def test_get_adaptive_recommendation(self):
        with patch(
            "backend.app.api.adaptive.adaptive_learning_loop_service.generate_adaptive_recommendation",
            return_value={
                "user_id": "507f1f77bcf86cd799439011",
                "action": "review_summary",
                "recommendation_type": "chunk",
                "recommendation_mode": "quick_review",
                "items": [{"chunk_id": "chunk-1", "estimated_read_time": 6}],
                "reason": "Summary first.",
                "target_concepts": ["loops"],
                "estimated_total_time": 6,
                "lesson_id": "lesson-1",
                "resource_id": None,
            },
        ):
            response = self.client.get("/api/adaptive/recommendation?lesson_id=lesson-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendation_type"], "chunk")


if __name__ == "__main__":
    unittest.main()
