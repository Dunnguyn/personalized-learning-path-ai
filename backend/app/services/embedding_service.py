import os
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime
from bson import ObjectId

from backend.app.database.mongo import get_db

# ==================================================
# CONFIG
# ==================================================
EMBEDDING_DIM = 384
USE_EXTERNAL_EMBEDDING = False   # Future: OpenAI / Gemini


# ==================================================
# VECTOR UTILS
# ==================================================
def normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v if norm == 0 else v / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ==================================================
# EMBEDDING
# ==================================================
def embed_text(text: str) -> List[float]:
    """
    Generate embedding vector for text.

    Current strategy:
    - Deterministic hash-based embedding (stable, free)

    Future:
    - OpenAI / Gemini embedding
    """

    if USE_EXTERNAL_EMBEDDING:
        raise NotImplementedError("External embedding not enabled")

    np.random.seed(abs(hash(text)) % (10**6))
    vec = np.random.rand(EMBEDDING_DIM)
    return normalize(vec).tolist()


# ==================================================
# STORE RESOURCE (VECTOR STORE)
# ==================================================
def store_resource(
    title: str,
    content: str,
    topic: str,
    level: str = "beginner",
    source: str = "manual"
) -> Dict:
    """
    Store learning resource with embedding.
    This function ONLY handles:
    - embedding
    - minimal metadata
    """

    db = get_db()
    vector = embed_text(content)

    doc = {
        "title": title,
        "content": content,
        "topic": topic,
        "level": level,
        "source": source,
        "embedding": vector,
        "created_at": datetime.utcnow()
    }

    result = db.resources.insert_one(doc)

    # Serialize ObjectId for safe return
    doc["_id"] = str(result.inserted_id)
    return doc


# ==================================================
# SEMANTIC SEARCH
# ==================================================
def semantic_search(
    query: str,
    k: int = 5,
    min_score: float = 0.75,
    topic: Optional[str] = None,
    level: Optional[str] = None
) -> List[Dict]:
    """
    Semantic search using cosine similarity.

    Steps:
    1. Embed query
    2. Compare with stored embeddings
    3. Filter by score + optional metadata
    """

    db = get_db()
    query_vec = np.array(embed_text(query))
    results = []

    mongo_filter = {}
    if topic:
        mongo_filter["topic"] = topic
    if level:
        mongo_filter["level"] = level

    cursor = db.resources.find(
        mongo_filter,
        {
            "embedding": 1,
            "title": 1,
            "content": 1,
            "topic": 1,
            "level": 1,
            "source": 1
        }
    )

    for doc in cursor:
        emb = np.array(doc.get("embedding", []))
        if emb.size == 0:
            continue

        score = cosine_similarity(query_vec, emb)

        if score >= min_score:
            results.append({
                "resource_id": str(doc["_id"]),
                "title": doc["title"],
                "snippet": doc["content"][:300],  # 🔥 avoid long content
                "topic": doc["topic"],
                "level": doc["level"],
                "source": doc["source"],
                "score": round(score, 4)
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]
