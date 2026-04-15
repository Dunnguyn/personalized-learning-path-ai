from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from typing import Dict, List, Any
import logging

from backend.app.api.auth import require_admin_user
from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/concepts", tags=["Concepts"])


def _build_prereq_map(db) -> Dict[str, List[str]]:
    prereq_map: Dict[str, List[str]] = {}
    for item in db.prerequisites.find({}, {"_id": 0}):
        to_id = str(item.get("to_concept_id") or "").strip()
        from_id = str(item.get("from_concept_id") or "").strip()
        if not to_id or not from_id:
            continue
        prereq_map.setdefault(to_id, []).append(from_id)
    return prereq_map


@router.get("", status_code=status.HTTP_200_OK)
def list_concepts(subject_id: str | None = Query(default=None)):
    """Return all concepts with prerequisites for graph display."""
    db = get_db()
    query: Dict[str, Any] = {}
    if subject_id:
        normalized = str(subject_id).strip().lower()
        query = {
            "$or": [
                {"subject_id": normalized},
                {"topic": normalized},
                {"metadata.subject_id": normalized},
                {"metadata.subject_key": normalized},
            ]
        }
    concepts = list(db.concepts.find(query, {"_id": 0}))
    prereq_map = _build_prereq_map(db)

    for concept in concepts:
        concept_id = str(concept.get("concept_id") or "").strip()
        concept["prerequisites"] = prereq_map.get(concept_id, [])

    return {"success": True, "concepts": concepts, "total": len(concepts)}


@router.get("/{concept_id}", status_code=status.HTTP_200_OK)
def get_concept(concept_id: str):
    """Return a single concept by concept_id."""
    db = get_db()
    concept = db.concepts.find_one(
        {"$or": [{"concept_id": concept_id}, {"concept_id": int(concept_id)}]}
        if str(concept_id).isdigit()
        else {"concept_id": concept_id},
        {"_id": 0},
    )

    if not concept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found"
        )

    prereq_map = _build_prereq_map(db)
    concept["prerequisites"] = prereq_map.get(str(concept.get("concept_id") or concept_id), [])

    return {"success": True, "concept": concept}


@router.get("/admin-graph/prerequisite-graph", status_code=status.HTTP_200_OK)
def get_admin_prerequisite_graph(
    subject_id: str | None = Query(default=None),
    current_user=Depends(require_admin_user),
):
    """Return concept nodes and prerequisite edges for admin editing."""
    del current_user
    payload = list_concepts(subject_id=subject_id)
    concepts = payload.get("concepts") or []
    edges = []
    for concept in concepts:
        to_id = str(concept.get("concept_id") or "").strip()
        for from_id in concept.get("prerequisites") or []:
            edges.append(
                {
                    "from_concept_id": str(from_id),
                    "to_concept_id": to_id,
                }
            )
    return {
        "success": True,
        "concepts": concepts,
        "edges": edges,
        "total_concepts": len(concepts),
        "total_edges": len(edges),
    }


@router.put("/{concept_id}/prerequisites", status_code=status.HTTP_200_OK)
def update_concept_prerequisites(
    concept_id: str,
    payload: Dict[str, Any] = Body(...),
    current_user=Depends(require_admin_user),
):
    """Replace prerequisite edges for a concept so admin can manage the graph."""
    del current_user
    db = get_db()

    concept = db.concepts.find_one({"concept_id": concept_id}, {"_id": 0})
    if not concept and str(concept_id).isdigit():
        concept = db.concepts.find_one({"concept_id": int(concept_id)}, {"_id": 0})
    if not concept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Concept not found",
        )

    normalized_concept_id = str(concept.get("concept_id") or concept_id).strip()
    prerequisite_values = payload.get("prerequisites")
    if prerequisite_values is None:
        prerequisite_values = []
    if not isinstance(prerequisite_values, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prerequisites must be an array",
        )

    normalized_prerequisites: List[str] = []
    seen: set[str] = set()
    for item in prerequisite_values:
        value = str(item or "").strip()
        if not value or value == normalized_concept_id or value in seen:
            continue
        seen.add(value)
        normalized_prerequisites.append(value)

    db.prerequisites.delete_many({"to_concept_id": normalized_concept_id})
    if normalized_prerequisites:
        db.prerequisites.insert_many(
            [
                {
                    "from_concept_id": prerequisite_id,
                    "to_concept_id": normalized_concept_id,
                }
                for prerequisite_id in normalized_prerequisites
            ]
        )

    concept["prerequisites"] = normalized_prerequisites
    return {
        "success": True,
        "concept": concept,
        "updated_prerequisite_count": len(normalized_prerequisites),
    }
