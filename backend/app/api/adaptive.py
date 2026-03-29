"""Adaptive learning loop API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user, resolve_user_role
from backend.app.api.schemas import (
    AdaptiveNextActionResponse,
    AdaptiveRecommendationResponse,
    AdaptiveRecomputeRequest,
    AdaptiveRecomputeResponse,
    LearnerStateSnapshotResponse,
    LearningEventIngestRequest,
    LearningEventResponse,
)
from backend.app.services.adaptive_learning_loop_service import (
    adaptive_learning_loop_service,
)

router = APIRouter(prefix="/adaptive", tags=["Adaptive Learning Loop"])


def _resolve_effective_user_id(
    requested_user_id: Optional[str],
    current_user: dict,
) -> str:
    authenticated_user_id = str(current_user.get("_id") or "")
    if not requested_user_id or str(requested_user_id).strip() == "":
        return authenticated_user_id
    if str(requested_user_id) == authenticated_user_id:
        return authenticated_user_id
    if resolve_user_role(current_user) == "admin":
        return str(requested_user_id)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post(
    "/events",
    response_model=LearningEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_learning_event(
    payload: LearningEventIngestRequest,
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id") or "")
    try:
        return adaptive_learning_loop_service.ingest_learning_event(
            user_id=user_id,
            event_type=payload.event_type.value,
            resource_id=payload.resource_id,
            lesson_id=payload.lesson_id,
            path_id=payload.path_id,
            concept_ids=payload.concept_ids,
            metadata=payload.metadata,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not ingest learning event.",
        ) from exc


@router.get(
    "/next-action",
    response_model=AdaptiveNextActionResponse,
    status_code=status.HTTP_200_OK,
)
def get_next_best_action(
    user_id: Optional[str] = Query(None),
    lesson_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        snapshot = adaptive_learning_loop_service.snapshot_repository.get_latest(
            effective_user_id
        ) or adaptive_learning_loop_service.update_learner_state(user_id=effective_user_id)
        return adaptive_learning_loop_service.decide_next_best_action(
            user_id=effective_user_id,
            learner_snapshot=snapshot,
            lesson_id=lesson_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not determine next best action.",
        ) from exc


@router.get(
    "/recommendation",
    response_model=AdaptiveRecommendationResponse,
    status_code=status.HTTP_200_OK,
)
def get_adaptive_recommendation(
    user_id: Optional[str] = Query(None),
    lesson_id: Optional[str] = Query(None),
    goal: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        return adaptive_learning_loop_service.generate_adaptive_recommendation(
            user_id=effective_user_id,
            lesson_id=lesson_id,
            goal=goal,
            level=level,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate adaptive recommendation.",
        ) from exc


@router.get(
    "/learner-state",
    response_model=LearnerStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
def get_latest_learner_state(
    user_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    snapshot = adaptive_learning_loop_service.snapshot_repository.get_latest(
        effective_user_id
    )
    if not snapshot:
        snapshot = adaptive_learning_loop_service.update_learner_state(
            user_id=effective_user_id
        )
    return snapshot


@router.post(
    "/recompute",
    response_model=AdaptiveRecomputeResponse,
    status_code=status.HTTP_200_OK,
)
def recompute_learner_state(
    payload: AdaptiveRecomputeRequest,
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(payload.user_id, current_user)
    try:
        snapshot = adaptive_learning_loop_service.update_learner_state(
            user_id=effective_user_id
        )
        action = adaptive_learning_loop_service.decide_next_best_action(
            user_id=effective_user_id,
            learner_snapshot=snapshot,
        )
        adaptive_learning_loop_service._persist_last_action(
            effective_user_id,
            action["next_best_action"],
        )
        return {"user_id": effective_user_id, "snapshot": snapshot, "next_action": action}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not recompute learner state.",
        ) from exc
