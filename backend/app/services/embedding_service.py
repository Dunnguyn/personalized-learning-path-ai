import os
import numpy as np
from typing import List, Dict
from backend.app.database.mongo import get_db

# ==================================================
# CONFIG
# ==================================================
EMBEDDING_DIM = 384
USE_EXTERNAL_EMBEDDING = False   # ⚠️ hiện tại Gemini embedding chưa ổn định

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

    Strategy:
    - Phase 1 (current): deterministic hash-based embedding
    - Phase 2 (future): Gemini / OpenAI embedding
    """

    # ===== FUTURE EXTENSION POINT =====
    if USE_EXTERNAL_EMBEDDING:
        raise NotImplementedError("External embedding not enabled")

    # ===== FALLBACK (STABLE & FREE) =====
    np.random.seed(abs(hash(text)) % (10**6))
    vec = np.random.rand(EMBEDDING_DIM)
    return normalize(vec).tolist()


# ==================================================
# STORE RESOURCE
# ==================================================
def store_resource(
    title: str,
    content: str,
    topic: str,
    level: str = "beginner",
    source: str = "manual"
) -> Dict:
    """
    Store learning resource with embedding
    """
    db = get_db()
    vector = embed_text(content)

    doc = {
        "title": title,
        "content": content,
        "topic": topic,
        "level": level,
        "source": source,
        "embedding": vector
    }

    db.resources.insert_one(doc)
    return doc


# ==================================================
# SEMANTIC SEARCH
# ==================================================
def semantic_search(
    query: str,
    k: int = 5,
    min_score: float = 0.75
) -> List[Dict]:
    """
    Semantic search using cosine similarity

    - Compute embedding for query once
    - Compare with stored embeddings
    - Filter by min_score
    """
    db = get_db()
    query_vec = np.array(embed_text(query))

    results = []

    for doc in db.resources.find({}, {"_id": 0, "embedding": 1, "title": 1,
                                      "content": 1, "topic": 1,
                                      "level": 1, "source": 1}):

        emb = np.array(doc.get("embedding", []))
        if emb.size == 0:
            continue

        score = cosine_similarity(query_vec, emb)

        if score >= min_score:
            results.append({
                "title": doc["title"],
                "content": doc["content"],
                "topic": doc["topic"],
                "level": doc["level"],
                "source": doc["source"],
                "score": round(score, 4)
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]
