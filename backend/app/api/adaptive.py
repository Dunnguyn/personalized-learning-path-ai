"""Adaptive learning loop API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user, require_admin_user, resolve_user_role
from backend.app.api.schemas import (
    AdaptiveExplanationResponse,
    AdaptiveNextActionResponse,
    AdaptivePathScopeAuditResponse,
    AdaptivePathScopeBackfillRequest,
    AdaptivePathScopeBackfillResponse,
    AdaptiveNextStepRequest,
    AdaptiveNextStepResponse,
    AdaptiveRecommendationResponse,
    LearnerStateSnapshotResponse,
    LearningEventIngestRequest,
    LearningEventResponse,
)
from backend.app.services.adaptive_learning_loop_service import (
    adaptive_learning_loop_service,
)
from backend.app.jobs.backfill_adaptive_path_scope_job import (
    backfill_adaptive_path_scope_job,
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
def record_learning_event(
    payload: LearningEventIngestRequest,
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(payload.user_id, current_user)
    try:
        return adaptive_learning_loop_service.record_event(
            {
                "user_id": effective_user_id,
                "event_type": payload.event_type.value,
                "path_id": payload.path_id,
                "lesson_id": payload.lesson_id,
                "resource_id": payload.resource_id,
                "question_id": payload.question_id,
                "concept_ids": payload.concept_ids,
                "payload": payload.payload.model_dump(exclude_none=True),
                "metadata": payload.metadata.model_dump(exclude_none=True),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record learning event.",
        ) from exc


@router.post(
    "/recompute-state/{user_id}",
    response_model=LearnerStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
def recompute_state(
    user_id: str,
    path_id: str = Query(...),
    lesson_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        return adaptive_learning_loop_service.recompute_state(
            effective_user_id,
            path_id,
            lesson_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not recompute learner state.",
        ) from exc


@router.get(
    "/state/{user_id}",
    response_model=LearnerStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
def get_latest_state(
    user_id: str,
    path_id: str = Query(...),
    lesson_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        snapshot = adaptive_learning_loop_service.get_latest_state(
            user_id=effective_user_id,
            path_id=path_id,
            lesson_id=lesson_id,
        )
        if not snapshot:
            snapshot = adaptive_learning_loop_service.recompute_state(
                effective_user_id,
                path_id,
                lesson_id,
            )
        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load learner state.",
        ) from exc


@router.post(
    "/next-step",
    response_model=AdaptiveNextStepResponse,
    status_code=status.HTTP_200_OK,
)
def get_next_step(
    payload: AdaptiveNextStepRequest,
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(payload.user_id, current_user)
    try:
        return adaptive_learning_loop_service.run_next_step(
            effective_user_id,
            payload.path_id,
            payload.lesson_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not determine the next adaptive step.",
        ) from exc


@router.get(
    "/explanations/{user_id}",
    response_model=AdaptiveExplanationResponse,
    status_code=status.HTTP_200_OK,
)
def get_adaptive_explanation(
    user_id: str,
    path_id: str = Query(...),
    lesson_id: str = Query(...),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        return adaptive_learning_loop_service.get_adaptive_explanation(
            effective_user_id,
            path_id,
            lesson_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load adaptive explanation.",
        ) from exc


@router.get(
    "/next-action",
    response_model=AdaptiveNextActionResponse,
    status_code=status.HTTP_200_OK,
)
def get_next_best_action(
    user_id: Optional[str] = Query(None),
    path_id: Optional[str] = Query(None),
    lesson_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        snapshot = adaptive_learning_loop_service.get_latest_state(
            user_id=effective_user_id,
            path_id=path_id,
            lesson_id=lesson_id,
        ) or adaptive_learning_loop_service.update_learner_state(
            user_id=effective_user_id,
            path_id=path_id,
        )
        return adaptive_learning_loop_service.decide_next_best_action(
            user_id=effective_user_id,
            path_id=path_id,
            learner_snapshot=snapshot,
            lesson_id=lesson_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    path_id: Optional[str] = Query(None),
    lesson_id: Optional[str] = Query(None),
    goal: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    try:
        return adaptive_learning_loop_service.generate_adaptive_recommendation(
            user_id=effective_user_id,
            path_id=path_id,
            lesson_id=lesson_id,
            goal=goal,
            level=level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
def get_legacy_latest_learner_state(
    user_id: Optional[str] = Query(None),
    path_id: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    effective_user_id = _resolve_effective_user_id(user_id, current_user)
    snapshot = adaptive_learning_loop_service.get_latest_state(
        user_id=effective_user_id,
        path_id=path_id,
    )
    if not snapshot:
        snapshot = adaptive_learning_loop_service.update_learner_state(
            user_id=effective_user_id,
            path_id=path_id,
        )
    return snapshot


@router.post(
    "/admin/backfill-path-scope",
    response_model=AdaptivePathScopeBackfillResponse,
    status_code=status.HTTP_200_OK,
)
def run_adaptive_path_scope_backfill(
    payload: AdaptivePathScopeBackfillRequest,
    current_user=Depends(require_admin_user),
):
    del current_user
    try:
        return backfill_adaptive_path_scope_job.run(
            user_id=payload.user_id,
            dry_run=payload.dry_run,
            limit=payload.limit,
            collection=payload.collection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not run adaptive path scope backfill.",
        ) from exc


@router.get(
    "/admin/backfill-path-scope/audit",
    response_model=AdaptivePathScopeAuditResponse,
    status_code=status.HTTP_200_OK,
)
def audit_adaptive_path_scope_backfill(
    user_id: Optional[str] = Query(None),
    sample_limit: int = Query(5, ge=1, le=20),
    collection: str = Query("all"),
    current_user=Depends(require_admin_user),
):
    del current_user
    try:
        return backfill_adaptive_path_scope_job.audit(
            user_id=user_id,
            sample_limit=sample_limit,
            collection=collection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not audit adaptive path scope backfill.",
        ) from exc
