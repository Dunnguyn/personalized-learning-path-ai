from fastapi import APIRouter, HTTPException, status
from typing import Dict, List
import logging

from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/concepts", tags=["Concepts"])


def _build_prereq_map(db) -> Dict[int, List[int]]:
    prereq_map: Dict[int, List[int]] = {}
    for item in db.prerequisites.find({}, {"_id": 0}):
        to_id = item.get("to_concept_id")
        from_id = item.get("from_concept_id")
        if to_id is None or from_id is None:
            continue
        prereq_map.setdefault(to_id, []).append(from_id)
    return prereq_map


@router.get("", status_code=status.HTTP_200_OK)
def list_concepts():
    """Return all concepts with prerequisites for graph display."""
    db = get_db()
    concepts = list(db.concepts.find({}, {"_id": 0}))
    prereq_map = _build_prereq_map(db)

    for concept in concepts:
        concept_id = concept.get("concept_id")
        concept["prerequisites"] = prereq_map.get(concept_id, [])

    return {
        "success": True,
        "concepts": concepts,
        "total": len(concepts)
    }


@router.get("/{concept_id}", status_code=status.HTTP_200_OK)
def get_concept(concept_id: int):
    """Return a single concept by concept_id."""
    db = get_db()
    concept = db.concepts.find_one({"concept_id": concept_id}, {"_id": 0})

    if not concept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Concept not found"
        )

    prereq_map = _build_prereq_map(db)
    concept["prerequisites"] = prereq_map.get(concept_id, [])

    return {
        "success": True,
        "concept": concept
    }
