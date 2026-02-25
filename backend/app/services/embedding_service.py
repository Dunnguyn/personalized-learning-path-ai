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

# Optional ChromaDB persistence
CHROMA_AVAILABLE = False
CHROMA_PATH = os.getenv("CHROMA_PATH", "backend/.chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "learning_resources")
_chroma_collection = None

try:
    import importlib

    chromadb = importlib.import_module("chromadb")
    _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    _chroma_collection = _chroma_client.get_or_create_collection(name=CHROMA_COLLECTION)
    CHROMA_AVAILABLE = True
    logger.info("ChromaDB enabled: %s", CHROMA_COLLECTION)
except Exception as e:
    logger.warning("ChromaDB not available: %s", e)

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
    bloom_level: Optional[str] = None,
    thumbnail: Optional[str] = None,
    pdf_file_path: Optional[str] = None
) -> Dict:
    """
    Store learning resource with embedding and minimal metadata.
    Returns the stored document with `resource_id` as string.
    
    Parameters:
    -----------
    thumbnail : str, optional
        Base64-encoded thumbnail image for PDFs (data:image/png;base64,...)
    pdf_file_path : str, optional
        File path to the original PDF file for serving via download endpoint
    """
    db = get_db()
    if content is None:
        content = title or ""
    
    try:
        vector = embed_text(content)
        
        if len(vector) != EMBEDDING_DIM:
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
        "thumbnail": thumbnail,
        "pdf_file_path": pdf_file_path,
        "created_at": datetime.utcnow()
    }

    try:
        result = db.resources.insert_one(doc)
        resource_id = str(result.inserted_id)
        
        doc["resource_id"] = resource_id
        doc["_id"] = resource_id

        if CHROMA_AVAILABLE and _chroma_collection is not None:
            try:
                _chroma_collection.add(
                    ids=[resource_id],
                    embeddings=[vector],
                    documents=[content],
                    metadatas=[{
                        "title": title,
                        "topic": topic,
                        "level": level,
                        "source": source,
                        "url": url or ""
                    }]
                )
            except Exception as e:
                logger.warning("ChromaDB add failed: %s", e)

        return doc
    except Exception as e:
        logger.exception("Failed to insert resource into DB: %s", e)
        raise


def store_embedding_only(
    content: str,
    parent_resource_id: str,
    chunk_index: int,
    topic: str,
    level: str = "beginner",
    metadata: Optional[Dict] = None
) -> str:
    """
    Store chunk embedding only (for search), without creating a visible resource.
    Used for PDF chunks where we want 1 visible resource but many searchable chunks.
    
    Returns embedding_id as string.
    """
    db = get_db()
    
    try:
        vector = embed_text(content)
        
        if len(vector) != EMBEDDING_DIM:
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
        "parent_resource_id": parent_resource_id,
        "chunk_index": chunk_index,
        "content": content,
        "topic": topic,
        "level": level,
        "embedding": vector,
        "metadata": metadata or {},
        "created_at": datetime.utcnow()
    }
    
    try:
        result = db.embeddings.insert_one(doc)
        embedding_id = str(result.inserted_id)
        
        # Also add to ChromaDB if available
        if CHROMA_AVAILABLE and _chroma_collection is not None:
            try:
                _chroma_collection.add(
                    ids=[embedding_id],
                    embeddings=[vector],
                    documents=[content],
                    metadatas=[{
                        "parent_resource_id": parent_resource_id,
                        "chunk_index": str(chunk_index),
                        "topic": topic,
                        "level": level
                    }]
                )
            except Exception as e:
                logger.warning("ChromaDB add failed: %s", e)
        
        return embedding_id
    except Exception as e:
        logger.exception("Error storing embedding: %s", e)
        raise


def store_resources_batch(resources: List[Dict]) -> Dict[str, int]:
    """
    Store multiple resources in a single batch operation (much faster).
    
    Args:
        resources: List of dicts with keys: title, content, topic, level, source, etc.
        
    Returns:
        Dict with inserted_count and failed_count
    """
    if not resources:
        return {"inserted_count": 0, "failed_count": 0}
    
    db = get_db()
    docs_to_insert = []
    chroma_data = {"ids": [], "embeddings": [], "documents": [], "metadatas": []}
    
    logger.info(f"Batch processing {len(resources)} resources for storage")
    
    # Prepare all documents
    for idx, res in enumerate(resources):
        try:
            content = res.get("content") or res.get("title") or ""
            
            # Generate embedding
            vector = embed_text(content)
            if len(vector) != EMBEDDING_DIM:
                vec = np.array(vector)
                if vec.size < EMBEDDING_DIM:
                    pad = np.zeros(EMBEDDING_DIM - vec.size)
                    vec = np.concatenate([vec, pad])
                else:
                    vec = vec[:EMBEDDING_DIM]
                vector = vec.tolist()
            
            doc = {
                "title": res.get("title", ""),
                "content": content,
                "topic": res.get("topic", ""),
                "level": res.get("level", "beginner"),
                "source": res.get("source", "pdf"),
                "embedding": vector,
                "concept_id": res.get("concept_id"),
                "url": res.get("url"),
                "pedagogy_type": res.get("pedagogy_type"),
                "bloom_level": res.get("bloom_level"),
                "created_at": datetime.utcnow()
            }
            
            docs_to_insert.append(doc)
            
            if idx % 20 == 0 and idx > 0:
                logger.info(f"  Prepared {idx}/{len(resources)} documents...")
                
        except Exception as e:
            logger.warning(f"Error preparing resource {idx}: {e}")
            continue
    
    if not docs_to_insert:
        return {"inserted_count": 0, "failed_count": len(resources)}
    
    # Batch insert into MongoDB
    try:
        logger.info(f"Inserting {len(docs_to_insert)} documents into MongoDB...")
        result = db.resources.insert_many(docs_to_insert, ordered=False)
        inserted_ids = result.inserted_ids
        logger.info(f"✅ Batch insert successful: {len(inserted_ids)} documents")
        
        # Prepare ChromaDB data if available
        if CHROMA_AVAILABLE and _chroma_collection is not None:
            try:
                for doc, doc_id in zip(docs_to_insert, inserted_ids):
                    chroma_data["ids"].append(str(doc_id))
                    chroma_data["embeddings"].append(doc["embedding"])
                    chroma_data["documents"].append(doc["content"])
                    chroma_data["metadatas"].append({
                        "title": doc["title"],
                        "topic": doc["topic"],
                        "level": doc["level"],
                        "source": doc["source"],
                        "url": doc.get("url") or ""
                    })
                
                logger.info(f"Adding {len(chroma_data['ids'])} documents to ChromaDB...")
                _chroma_collection.add(**chroma_data)
                logger.info(f"✅ ChromaDB batch add successful")
            except Exception as e:
                logger.warning(f"ChromaDB batch add failed: {e}")
        
        return {
            "inserted_count": len(inserted_ids),
            "failed_count": len(resources) - len(docs_to_insert)
        }
        
    except Exception as e:
        logger.exception(f"Batch insert failed: {e}")
        return {
            "inserted_count": 0,
            "failed_count": len(resources)
        }


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
    - Search in BOTH resources collection AND embeddings collection (chunks)
    - For chunks, fetch parent_resource and deduplicate
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
        db.embeddings.create_index([("parent_resource_id", 1)])
        db.embeddings.create_index([("topic", 1)])
        db.embeddings.create_index([("level", 1)])
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

    # Track best score per resource_id for deduplication
    resource_scores = {}  # resource_id -> {score, doc}

    # 1. SEARCH IN RESOURCES COLLECTION
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
                "created_at": 1,
                "thumbnail": 1,
                "pdf_file_path": 1
            }
        ).limit(candidate_limit)
        
        for doc in cursor:
            emb = doc.get("embedding") or []
            try:
                emb_arr = np.array(emb, dtype=float)
                if emb_arr.size != EMBEDDING_DIM:
                    continue
                score = cosine_similarity(query_vec, emb_arr)
                if score >= min_score:
                    resource_id = str(doc.get("_id") or doc.get("resource_id"))
                    if resource_id not in resource_scores or score > resource_scores[resource_id]["score"]:
                        resource_scores[resource_id] = {
                            "score": score,
                            "doc": doc
                        }
            except Exception as e:
                logger.debug("Error scoring resource doc %s: %s", doc.get("_id"), e)
                continue
    except Exception as e:
        logger.exception("DB query failed in semantic_search (resources): %s", e)

    # 2. SEARCH IN EMBEDDINGS COLLECTION (CHUNKS)
    try:
        embedding_cursor = db.embeddings.find(
            mongo_filter,
            {
                "embedding": 1,
                "parent_resource_id": 1,
                "content": 1,
                "chunk_index": 1
            }
        ).limit(candidate_limit * 2)  # More candidates since chunks are smaller
        
        for doc in embedding_cursor:
            emb = doc.get("embedding") or []
            try:
                emb_arr = np.array(emb, dtype=float)
                if emb_arr.size != EMBEDDING_DIM:
                    continue
                score = cosine_similarity(query_vec, emb_arr)
                if score >= min_score:
                    parent_id = doc.get("parent_resource_id")
                    if not parent_id:
                        continue
                    
                    # Fetch parent resource if not already in results or if this chunk has better score
                    if parent_id not in resource_scores or score > resource_scores[parent_id]["score"]:
                        # Fetch full resource document
                        try:
                            from bson import ObjectId
                            parent_doc = db.resources.find_one({"_id": ObjectId(parent_id)})
                            if parent_doc:
                                resource_scores[parent_id] = {
                                    "score": score,
                                    "doc": parent_doc,
                                    "matched_chunk": doc.get("chunk_index", 0)
                                }
                        except Exception as e:
                            logger.debug(f"Error fetching parent resource {parent_id}: {e}")
                            continue
            except Exception as e:
                logger.debug("Error scoring embedding doc %s: %s", doc.get("_id"), e)
                continue
    except Exception as e:
        logger.exception("DB query failed in semantic_search (embeddings): %s", e)

    # 3. BUILD RESULTS FROM DEDUPLICATED RESOURCES
    results = []
    for resource_id, data in resource_scores.items():
        doc = data["doc"]
        score = data["score"]
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
            "created_at": doc.get("created_at"),
            "thumbnail": doc.get("thumbnail"),
            "pdf_file_path": doc.get("pdf_file_path")
        })

    # sort and return top-k
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]