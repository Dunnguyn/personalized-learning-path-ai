"""Embedding utilities with caching and optional vector-store integration."""

from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
EMBEDDING_CACHE_SIZE = int(os.getenv("EMBEDDING_CACHE_SIZE", "2048"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
USE_EXTERNAL_EMBEDDING = os.getenv("USE_EXTERNAL_EMBEDDING", "false").lower() == "true"
CHROMA_PATH = os.getenv("CHROMA_PATH", "backend/.chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "learning_resource_chunks")


def normalize(vector: np.ndarray) -> np.ndarray:
    """Return L2-normalized vector."""
    norm = np.linalg.norm(vector)
    if norm == 0 or np.isnan(norm):
        return vector
    return vector / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Compute cosine similarity for two vectors."""
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0 or np.isnan(denom):
        return 0.0
    return float(np.dot(left, right) / denom)


def compute_content_hash(text: str) -> str:
    """Create stable SHA256 hash for text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_file_hash(file_path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Create stable SHA256 hash for a file."""
    digest = hashlib.sha256()
    path = Path(file_path)
    with path.open("rb") as file_obj:
        while True:
            block = file_obj.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class _LRUEmbeddingCache:
    """Thread-safe in-memory LRU cache for embeddings."""

    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        self._data: "OrderedDict[str, List[float]]" = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[List[float]]:
        with self._lock:
            value = self._data.get(key)
            if value is None:
                return None
            self._data.move_to_end(key)
            return list(value)

    def set(self, key: str, value: List[float]) -> None:
        with self._lock:
            self._data[key] = list(value)
            self._data.move_to_end(key)
            if len(self._data) > self.max_size:
                self._data.popitem(last=False)


class ChromaVectorStore:
    """Optional Chroma-backed chunk vector store."""

    def __init__(self) -> None:
        self.available = False
        self.collection = None
        try:
            import importlib

            chromadb = importlib.import_module("chromadb")
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            self.collection = client.get_or_create_collection(name=CHROMA_COLLECTION)
            self.available = True
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Chroma vector store unavailable: %s", exc)

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        if not self.available or not self.collection or not chunks:
            return
        try:
            self.collection.upsert(
                ids=[chunk["id"] for chunk in chunks],
                embeddings=[chunk["embedding"] for chunk in chunks],
                documents=[chunk["content"] for chunk in chunks],
                metadatas=[chunk["metadata"] for chunk in chunks],
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Chroma upsert failed: %s", exc)

    def delete_chunks(self, ids: List[str]) -> None:
        if not self.available or not self.collection or not ids:
            return
        try:
            self.collection.delete(ids=ids)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Chroma delete failed: %s", exc)

    def query(
        self,
        query_embedding: List[float],
        *,
        limit: int,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.available or not self.collection:
            return []
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where,
            )
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]
            payload = []
            for item_id, distance, metadata, document in zip(ids, distances, metadatas, documents):
                payload.append(
                    {
                        "id": item_id,
                        "distance": distance,
                        "metadata": metadata or {},
                        "content": document,
                    }
                )
            return payload
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Chroma query failed: %s", exc)
            return []


class EmbeddingService:
    """Embedding service with batching, cache, and provider fallback."""

    def __init__(self) -> None:
        self.cache = _LRUEmbeddingCache(EMBEDDING_CACHE_SIZE)
        self.vector_store = ChromaVectorStore()

    def _fallback_embedding(self, text: str) -> List[float]:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)
        rng = np.random.RandomState(seed)
        vector = normalize(rng.rand(EMBEDDING_DIM).astype(float))
        return [float(item) for item in vector.tolist()]

    def _embed_with_provider(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("External embedding provider is not configured.")

    def embed_texts(self, texts: Iterable[str]) -> List[List[float]]:
        """Embed texts in batches and reuse cached vectors when possible."""
        materialized = [text or "" for text in texts]
        if not materialized:
            return []

        results: Dict[str, List[float]] = {}
        missing_hashes: Dict[str, str] = {}
        for text in materialized:
            content_hash = compute_content_hash(text)
            cached = self.cache.get(content_hash)
            if cached is not None:
                results[content_hash] = cached
            elif content_hash not in missing_hashes:
                missing_hashes[content_hash] = text

        if missing_hashes:
            missing_items = list(missing_hashes.items())
            for index in range(0, len(missing_items), EMBEDDING_BATCH_SIZE):
                batch = missing_items[index : index + EMBEDDING_BATCH_SIZE]
                batch_texts = [item[1] for item in batch]
                if USE_EXTERNAL_EMBEDDING:
                    try:
                        vectors = self._embed_with_provider(batch_texts)
                    except Exception as exc:
                        logger.warning(
                            "External embedding failed, using local fallback: %s",
                            exc,
                        )
                        vectors = [self._fallback_embedding(text) for text in batch_texts]
                else:
                    vectors = [self._fallback_embedding(text) for text in batch_texts]

                for (content_hash, _), vector in zip(batch, vectors):
                    padded = self._ensure_dimensionality(vector)
                    self.cache.set(content_hash, padded)
                    results[content_hash] = padded

        return [results[compute_content_hash(text)] for text in materialized]

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text."""
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else [0.0] * EMBEDDING_DIM

    @staticmethod
    def _ensure_dimensionality(vector: List[float]) -> List[float]:
        array = np.array(vector, dtype=float)
        if array.size < EMBEDDING_DIM:
            padding = np.zeros(EMBEDDING_DIM - array.size)
            array = np.concatenate([array, padding])
        elif array.size > EMBEDDING_DIM:
            array = array[:EMBEDDING_DIM]
        return [float(item) for item in normalize(array).tolist()]


embedding_service = EmbeddingService()
