from typing import List, Dict
import numpy as np

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import (
    embed_text,
    cosine_similarity
)


def recommend_resources_for_concept(
    concept_id: int,
    level: str,
    query: str = "",
    limit: int = 5
) -> List[Dict]:
    """
    Recommend học liệu cho 1 concept
    - Filter theo concept_id + level
    - Re-rank bằng semantic similarity (optional)
    """

    db = get_db()

    resources = list(db.resources.find(
        {
            "concept_id": concept_id,
            "level": level
        },
        {"_id": 0, "embedding": 1}
    ))

    if not resources:
        return []

    # ===== Semantic re-rank nếu có query =====
    if query:
        query_vec = np.array(embed_text(query))

        for r in resources:
            emb = np.array(r.get("embedding", []))
            if len(emb) == 0:
                r["score"] = 0
            else:
                r["score"] = cosine_similarity(query_vec, emb)

        resources.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ===== Format output =====
    result = []
    for r in resources[:limit]:
        result.append({
            "title": r.get("title"),
            "source": r.get("source"),
            "video_url": r.get("video_url"),
            "topic": r.get("topic"),
            "level": r.get("level"),
            "has_transcript": r.get("has_transcript", True),
            "score": round(r.get("score", 0), 4)
        })

    return result
