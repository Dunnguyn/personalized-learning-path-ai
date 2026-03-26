"""Evaluation APIs for experiments and baseline comparisons."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import get_current_user
from backend.app.services.evaluation_service import evaluation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


@router.get("/experiments", status_code=status.HTTP_200_OK)
def list_experiments(current_user=Depends(get_current_user)):
    """List experiments with assignment summaries."""
    del current_user
    try:
        return {
            "items": evaluation_service.list_experiments(),
            "total": len(evaluation_service.list_experiments()),
        }
    except Exception as exc:
        logger.exception("Failed to list experiments: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load experiments",
        ) from exc


@router.get("/experiments/{experiment_id}", status_code=status.HTTP_200_OK)
def get_experiment(experiment_id: str, current_user=Depends(get_current_user)):
    """Get one experiment with metric snapshot."""
    del current_user
    try:
        return evaluation_service.get_experiment(experiment_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to get experiment %s: %s", experiment_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load experiment",
        ) from exc


@router.post(
    "/experiments/{experiment_id}/assign/{user_id}", status_code=status.HTTP_200_OK
)
def assign_experiment_variant(
    experiment_id: str, user_id: str, current_user=Depends(get_current_user)
):
    """Assign user into experiment variant using stable hashing."""
    del current_user
    try:
        return evaluation_service.assign_user_variant(experiment_id, user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to assign experiment variant: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not assign experiment variant",
        ) from exc
