"""Backward-compatible import shim for the adaptive learning loop."""

from backend.app.services.adaptive.event_ingestion import (
    AdaptiveLearningLoopService,
    adaptive_learning_loop_service,
)

__all__ = [
    "AdaptiveLearningLoopService",
    "adaptive_learning_loop_service",
]
