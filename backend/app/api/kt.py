"""Knowledge tracing query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from bson import ObjectId

from backend.app.api.auth import get_current_user
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service

router = APIRouter(prefix="/kt", tags=["Knowledge Tracing"])


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


@router.get("/user/{user_id}/concepts", status_code=status.HTTP_200_OK)
def get_user_concept_kt_states(user_id: str, current_user=Depends(get_current_user)):
    _assert_same_user(user_id, current_user)
    states = knowledge_tracing_service.get_user_concept_states(
        user_id=user_id, limit=300
    )
    return {
        "user_id": user_id,
        "total": len(states),
        "items": _to_json_safe(states),
    }


@router.get("/user/{user_id}/lessons/{lesson_id}", status_code=status.HTTP_200_OK)
def get_user_lesson_kt_states(
    user_id: str, lesson_id: str, current_user=Depends(get_current_user)
):
    _assert_same_user(user_id, current_user)
    states = knowledge_tracing_service.get_user_lesson_states(
        user_id=user_id, lesson_id=lesson_id, limit=100
    )
    return {
        "user_id": user_id,
        "lesson_id": lesson_id,
        "total": len(states),
        "items": _to_json_safe(states),
    }
