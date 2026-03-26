"""Path refinement and intervention tracking endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from bson import ObjectId

from backend.app.api.auth import get_current_user
from backend.app.services.path_refinement_service import path_refinement_service

router = APIRouter(tags=["Path Refinement"])


def _to_json_safe(value):
    return jsonable_encoder(value, custom_encoder={ObjectId: str})


def _assert_same_user(request_user_id: str, current_user: dict) -> None:
    auth_object_id = str(current_user.get("_id", ""))
    auth_numeric_id = current_user.get("user_id")
    if request_user_id == auth_object_id:
        return
    if auth_numeric_id is not None and request_user_id == str(auth_numeric_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post("/path/refine/{path_id}", status_code=status.HTTP_200_OK)
def refine_path(
    path_id: str,
    lesson_id: Optional[str] = Query(default=None),
    trigger_reason: Optional[str] = Query(default=None),
    dry_run: bool = Query(default=False),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.get("_id", ""))
    try:
        result = path_refinement_service.refine_path(
            path_id=path_id,
            user_id=user_id,
            lesson_id=lesson_id,
            trigger_reason=trigger_reason,
            dry_run=dry_run,
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/path/refinement/{user_id}", status_code=status.HTTP_200_OK)
def get_refinement_actions(user_id: str, current_user=Depends(get_current_user)):
    _assert_same_user(user_id, current_user)
    items = path_refinement_service.list_refinement_actions(user_id=user_id, limit=200)
    return {
        "user_id": user_id,
        "total": len(items),
        "items": _to_json_safe(items),
    }


@router.get("/interventions/{user_id}", status_code=status.HTTP_200_OK)
def get_intervention_logs(user_id: str, current_user=Depends(get_current_user)):
    _assert_same_user(user_id, current_user)
    items = path_refinement_service.list_interventions(user_id=user_id, limit=200)
    return {
        "user_id": user_id,
        "total": len(items),
        "items": _to_json_safe(items),
    }
