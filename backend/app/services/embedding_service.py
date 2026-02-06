import os
import hashlib
import logging
from typing import List, Dict, Optional
from datetime import datetime
from functools import lru_cache

import numpy as np
from bson import ObjectId

from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ==================================================
# CONFIG
# ==================================================
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
USE_EXTERNAL_EMBEDDING = os.getenv("USE_EXTERNAL_EMBEDDING", "false").lower() == "true"
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "")  # e.g. "gemini" or "openai" (not implemented)
EMBEDDING_CACHE_SIZE = int(os.getenv("EMBEDDING_CACHE_SIZE", "1024"))

# ==================================================
# VECTOR UTILS
# ==================================================
def normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    if norm == 0 or np.isnan(norm):
        return v
    return v / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    try:
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0 or np.isnan(denom):
            return 0.0
        return float(np.dot(a, b) / denom)
    except Exception as e:
        logger.debug("cosine_similarity error: %s", e)
        return 0.0


# ==================================================
# EMBEDDING (deterministic fallback + provider stub)
# ==================================================
def _hash_seed_from_text(text: str) -> int:
    # stable seed based on md5
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16)  # use first 8 hex digits


@lru_cache(maxsize=EMBEDDING_CACHE_SIZE)
def _embed_text_fallback(text: str) -> tuple:
    """
    Deterministic hash-based embedding (fallback).
    Returns tuple of floats to be cacheable by lru_cache.
    """
    seed = _hash_seed_from_text(text)
    rng = np.random.RandomState(seed)
    vec = rng.rand(EMBEDDING_DIM).astype(float)
    vec = normalize(vec)
    return tuple(float(x) for x in vec)


def embed_text(text: str) -> List[float]:
    """
    Generate embedding vector for text.

    Strategy:
    - If USE_EXTERNAL_EMBEDDING is enabled and provider implemented, call provider.
    - Otherwise use deterministic hash-based fallback (stable, not semantic).
    """
    if not text:
        return [0.0] * EMBEDDING_DIM

    # Try external provider (not implemented here)
    if USE_EXTERNAL_EMBEDDING:
        try:
            # Placeholder: implement provider call (OpenAI/Gemini) here if desired
            # Example: call provider API and return normalized vector
            raise NotImplementedError("External embedding provider not configured in this environment.")
        except Exception as e:
            logger.warning("External embedding provider failed: %s — falling back to local embedding", e)

    # Fallback deterministic embedding (cached)
    try:
        vec_tuple = _embed_text_fallback(text)
        return list(vec_tuple)
    except Exception as e:
        logger.exception("Fallback embedding failed: %s", e)
        return [0.0] * EMBEDDING_DIM


# ==================================================
# STORE RESOURCE (VECTOR STORE)
# ==================================================
def store_resource(
    title: str,
    content: str,
    topic: str,
    level: str = "beginner",
    source: str = "manual",
    concept_id: Optional[int] = None,
    url: Optional[str] = None,
    pedagogy_type: Optional[str] = None,
    bloom_level: Optional[str] = None
) -> Dict:
    """
    Store learning resource with embedding and minimal metadata.
    Returns the stored document with `resource_id` as string.
    """
    db = get_db()
    if content is None:
        content = title or ""

    try:
        vector = embed_text(content)
        if len(vector) != EMBEDDING_DIM:
            logger.warning("Generated embedding length != EMBEDDING_DIM; padding/cropping applied")
            # pad or crop
            vec = np.array(vector)
            if vec.size < EMBEDDING_DIM:
                pad = np.zeros(EMBEDDING_DIM - vec.size)
                vec = np.concatenate([vec, pad])
            else:
                vec = vec[:EMBEDDING_DIM]
            vector = vec.tolist()
    except Exception as e:
        logger.exception("Error generating embedding: %s", e)
        vector = [0.0] * EMBEDDING_DIM

    doc = {
        "title": title,
        "content": content,
        "topic": topic,
        "level": level,
        "source": source,
        "embedding": vector,
        "concept_id": concept_id,
        "url": url,
        "pedagogy_type": pedagogy_type,
        "bloom_level": bloom_level,
        "created_at": datetime.utcnow()
    }

    try:
        result = db.resources.insert_one(doc)
        resource_id = str(result.inserted_id)
        doc["resource_id"] = resource_id
        doc["_id"] = resource_id
        logger.info("Stored resource: %s (topic=%s, level=%s)", title, topic, level)
        return doc
    except Exception as e:
        logger.exception("Failed to insert resource into DB: %s", e)
        raise


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

    - Embed query
    - Fetch candidate documents (filtered by topic/level)
    - Compute similarity and return top-k with score >= min_score
    """
    db = get_db()
    try:
        query_vec = np.array(embed_text(query))
    except Exception as e:
        logger.exception("Failed to embed query: %s", e)
        return []

    # Ensure indexes for faster filtering (idempotent)
    try:
        db.resources.create_index([("topic", 1)])
        db.resources.create_index([("level", 1)])
        db.resources.create_index([("created_at", -1)])
    except Exception:
        # indexes may already exist or user may lack permission
        pass

    mongo_filter = {}
    if topic:
        mongo_filter["topic"] = topic
    if level:
        mongo_filter["level"] = level
    mongo_filter["embedding"] = {"$exists": True}

    # Limit candidate scan to k * factor to reduce cost
    candidate_limit = max(k * 10, 50)

    try:
        cursor = db.resources.find(
            mongo_filter,
            {
                "embedding": 1,
                "title": 1,
                "content": 1,
                "topic": 1,
                "level": 1,
                "source": 1,
                "pedagogy_type": 1,
                "bloom_level": 1,
                "concept_id": 1,
                "url": 1,
                "created_at": 1
            }
        ).limit(candidate_limit)
    except Exception as e:
        logger.exception("DB query failed in semantic_search: %s", e)
        return []

    results = []
    for doc in cursor:
        emb = doc.get("embedding") or []
        try:
            emb_arr = np.array(emb, dtype=float)
            if emb_arr.size != EMBEDDING_DIM:
                logger.debug("Skipping doc with incompatible embedding size: %s", doc.get("_id"))
                continue
            score = cosine_similarity(query_vec, emb_arr)
            if score >= min_score:
                results.append({
                    "resource_id": str(doc.get("_id") or doc.get("resource_id")),
                    "title": doc.get("title"),
                    "snippet": (doc.get("content") or "")[:300],
                    "topic": doc.get("topic"),
                    "level": doc.get("level"),
                    "source": doc.get("source"),
                    "pedagogy_type": doc.get("pedagogy_type"),
                    "bloom_level": doc.get("bloom_level"),
                    "concept_id": doc.get("concept_id"),
                    "url": doc.get("url"),
                    "score": round(float(score), 4),
                    "created_at": doc.get("created_at")
                })
        except Exception as e:
            logger.debug("Error scoring doc %s: %s", doc.get("_id"), e)
            continue

    # sort and return top-k
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]