"""Centralized event-based logging service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import logging
import traceback

from backend.app.database.mongo import get_db
from backend.app.repositories.event_log_repository import EventLogRepository

logger = logging.getLogger(__name__)


class EventLoggingService:
    """High-level event logging facade used by API/services/middleware."""

    def __init__(self, repository: EventLogRepository):
        self.repository = repository

    def log_event(self, event_type: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "event_type": event_type,
            "timestamp": kwargs.pop("timestamp", datetime.now(timezone.utc)),
            "event_id": kwargs.pop("event_id", None),
            "user_id": kwargs.pop("user_id", None),
            "session_id": kwargs.pop("session_id", None),
            "subject_id": kwargs.pop("subject_id", None),
            "path_id": kwargs.pop("path_id", None),
            "chapter_id": kwargs.pop("chapter_id", None),
            "lesson_id": kwargs.pop("lesson_id", None),
            "concept_id": kwargs.pop("concept_id", None),
            "resource_id": kwargs.pop("resource_id", None),
            "duration_ms": kwargs.pop("duration_ms", None),
            "mastery_before": kwargs.pop("mastery_before", None),
            "mastery_after": kwargs.pop("mastery_after", None),
            "confidence_before": kwargs.pop("confidence_before", None),
            "confidence_after": kwargs.pop("confidence_after", None),
            "recommendation_score": kwargs.pop("recommendation_score", None),
            "rank_position": kwargs.pop("rank_position", None),
            "llm_model": kwargs.pop("llm_model", None),
            "token_input": kwargs.pop("token_input", None),
            "token_output": kwargs.pop("token_output", None),
            "cost_estimate": kwargs.pop("cost_estimate", None),
            "latency_ms": kwargs.pop("latency_ms", None),
            "success": kwargs.pop("success", None),
            "error_code": kwargs.pop("error_code", None),
            "metadata": kwargs.pop("metadata", {}),
        }

        payload.update(kwargs)
        payload = {key: value for key, value in payload.items() if value is not None}

        try:
            return self.repository.create_event(payload)
        except Exception as exc:
            logger.warning("Failed to log event %s: %s", event_type, exc)
            return None

    def log_api_event(
        self,
        *,
        event_type: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.log_event(
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            duration_ms=duration_ms,
            success=(status_code < 400),
            error_code=error_code,
            metadata={
                "method": method,
                "path": path,
                "status_code": status_code,
            },
        )

    def log_exception_event(
        self,
        *,
        event_type: str,
        error: Exception,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        details = dict(metadata or {})
        details["stack_trace"] = traceback.format_exc(limit=5)
        return self.log_event(
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            success=False,
            error_code=error.__class__.__name__,
            metadata=details,
        )


db = get_db()
event_log_repository = EventLogRepository(db)
event_logging_service = EventLoggingService(event_log_repository)
