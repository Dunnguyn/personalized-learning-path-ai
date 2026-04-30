"""Backward-compatible import shim for unified learning-path orchestration."""

from backend.app.services.learning_path.generator import (
    UnifiedLearningPathService,
    learning_path_service,
)

__all__ = [
    "UnifiedLearningPathService",
    "learning_path_service",
]
