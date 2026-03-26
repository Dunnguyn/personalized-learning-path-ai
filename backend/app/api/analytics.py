"""Analytics APIs for learner, admin, and system monitoring dashboards."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.services.analytics_service import analytics_service
from backend.app.services.event_logging_service import event_logging_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/learner/{user_id}", status_code=status.HTTP_200_OK)
def get_learner_dashboard(user_id: str, current_user=Depends(get_current_user)):
    """Return learner analytics dashboard data."""
    auth_user_id = str(current_user.get("_id", ""))
    if auth_user_id != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        data = analytics_service.get_learner_dashboard(user_id=user_id)
        event_logging_service.log_event(
            "recommendation_shown",
            user_id=auth_user_id,
            metadata={"source": "analytics_learner_dashboard"},
            success=True,
        )
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load learner analytics: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learner analytics",
        ) from exc


@router.get("/admin/overview", status_code=status.HTTP_200_OK)
def get_admin_overview(current_user=Depends(get_current_user)):
    """Return admin overview metrics."""
    del current_user
    try:
        return analytics_service.get_admin_overview()
    except Exception as exc:
        logger.exception("Failed to load admin overview: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load admin overview",
        ) from exc


@router.get("/admin/retention", status_code=status.HTTP_200_OK)
def get_admin_retention(current_user=Depends(get_current_user)):
    """Return retention metrics."""
    del current_user
    try:
        return analytics_service.get_admin_retention()
    except Exception as exc:
        logger.exception("Failed to load retention analytics: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load retention analytics",
        ) from exc


@router.get("/admin/recommendation", status_code=status.HTTP_200_OK)
def get_admin_recommendation(current_user=Depends(get_current_user)):
    """Return recommendation effectiveness metrics."""
    del current_user
    try:
        return analytics_service.get_admin_recommendation()
    except Exception as exc:
        logger.exception("Failed to load recommendation analytics: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load recommendation analytics",
        ) from exc


@router.get("/system/performance", status_code=status.HTTP_200_OK)
def get_system_performance(current_user=Depends(get_current_user)):
    """Return system performance and operational metrics."""
    del current_user
    try:
        return analytics_service.get_system_performance()
    except Exception as exc:
        logger.exception("Failed to load system performance: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load system performance",
        ) from exc
