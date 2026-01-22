import os
import numpy as np
from typing import List, Dict
from backend.app.database.mongo import get_db

# ===== Optional OpenAI Embedding =====
USE_EMBEDDING = True
try:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    USE_EMBEDDING = False
    client = None


# ===== Utilities =====
def normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v if norm == 0 else v / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ===== Core: Create Embedding =====
def embed_text(text: str) -> List[float]:
    """
    Sinh embedding cho 1 đoạn text.
    Ưu tiên OpenAI, fallback hash-based nếu không có key.
    """
    if USE_EMBEDDING and client:
        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
        except Exception:
            pass

    # ---------- Fallback ----------
    np.random.seed(abs(hash(text)) % (10**6))
    return normalize(np.random.rand(384)).tolist()


# ===== Store Resource =====
def store_resource(
    title: str,
    content: str,
    topic: str,
    level: str = "beginner",
    source: str = "manual"
) -> Dict:
    """
    Lưu học liệu + embedding vào MongoDB
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


# ===== Semantic Search (OPTIMIZED) =====
def semantic_search(
    query: str,
    k: int = 5,
    min_score: float = 0.75
) -> List[Dict]:
    """
    Tìm kiếm học liệu theo ngữ nghĩa (cosine similarity)
    - Lọc theo min_score
    - Không trả embedding
    """
    db = get_db()
    query_vec = np.array(embed_text(query))

    results = []

    for doc in db.resources.find({}, {"_id": 0}):
        emb = np.array(doc.get("embedding", []))
        if len(emb) == 0:
            continue

        score = cosine_similarity(query_vec, emb)

        if score >= min_score:
            results.append({
                "title": doc.get("title"),
                "content": doc.get("content"),
                "topic": doc.get("topic"),
                "level": doc.get("level"),
                "source": doc.get("source"),
                "score": round(score, 4)
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]
