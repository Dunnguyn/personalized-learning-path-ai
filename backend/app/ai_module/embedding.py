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

from backend.app.utils.gemini import get_gemini_client

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
EMBEDDING_CACHE_SIZE = int(os.getenv("EMBEDDING_CACHE_SIZE", "2048"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
USE_EXTERNAL_EMBEDDING = os.getenv("USE_EXTERNAL_EMBEDDING", "false").lower() == "true"
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
EMBEDDING_STRICT_MODE = os.getenv("EMBEDDING_STRICT_MODE", "").strip().lower()
SENTENCE_TRANSFORMER_MODEL = os.getenv(
    "SENTENCE_TRANSFORMER_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
).strip()
GEMINI_EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
).strip()
CHROMA_PATH = os.getenv("CHROMA_PATH", "backend/.runtime/chroma")
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


def resolve_gemini_embedding_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip()
    if normalized in {"models/text-embedding-004", "text-embedding-004"}:
        return "gemini-embedding-001"
    return normalized or "gemini-embedding-001"


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
            for item_id, distance, metadata, document in zip(
                ids, distances, metadatas, documents
            ):
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
        self._sentence_transformer = None
        self._gemini_client = None
        self.active_backend = "hash_fallback"
        self._last_validation_error: Optional[str] = None

    def _fallback_embedding(self, text: str) -> List[float]:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)
        rng = np.random.RandomState(seed)
        vector = normalize(rng.rand(EMBEDDING_DIM).astype(float))
        return [float(item) for item in vector.tolist()]

    def _load_sentence_transformer(self):
        if self._sentence_transformer is not None:
            return self._sentence_transformer
        try:
            from sentence_transformers import SentenceTransformer

            self._sentence_transformer = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("SentenceTransformer backend unavailable: %s", exc)
            self._sentence_transformer = False
        return self._sentence_transformer if self._sentence_transformer is not False else None

    def _load_gemini_client(self):
        if self._gemini_client is not None:
            return self._gemini_client
        try:
            client = get_gemini_client()
            if client is None:
                self._gemini_client = False
                return None
            self._gemini_client = client
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Gemini embedding backend unavailable: %s", exc)
            self._gemini_client = False
        return self._gemini_client if self._gemini_client is not False else None

    def _provider_candidates(self) -> List[str]:
        provider = EMBEDDING_PROVIDER or "auto"
        if provider == "hash":
            return ["hash"]
        if provider in {"sentence-transformers", "sentence_transformers"}:
            return ["sentence_transformers", "hash"]
        if provider == "gemini":
            return ["gemini", "hash"]
        if provider in {"auto", ""}:
            return ["sentence_transformers", "gemini", "hash"]
        if USE_EXTERNAL_EMBEDDING:
            return ["sentence_transformers", "gemini", "hash"]
        return ["sentence_transformers", "gemini", "hash"]

    @staticmethod
    def is_strict_mode_enabled() -> bool:
        if EMBEDDING_STRICT_MODE in {"1", "true", "yes", "on"}:
            return True
        if EMBEDDING_STRICT_MODE in {"0", "false", "no", "off"}:
            return False
        return ENVIRONMENT in {"production", "demo"}

    def _embed_with_sentence_transformers(self, texts: List[str]) -> List[List[float]]:
        model = self._load_sentence_transformer()
        if model is None:
            raise RuntimeError("sentence_transformers backend is not available")
        vectors = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        self.active_backend = "sentence_transformers"
        return [[float(item) for item in vector.tolist()] for vector in vectors]

    def _embed_with_gemini(self, texts: List[str]) -> List[List[float]]:
        client = self._load_gemini_client()
        if client is None:
            raise RuntimeError("gemini backend is not available")
        response = client.models.embed_content(
            model=resolve_gemini_embedding_model_name(GEMINI_EMBEDDING_MODEL),
            contents=texts,
        )
        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != len(texts):
            raise RuntimeError("gemini embedding response shape mismatch")
        vectors: List[List[float]] = []
        for item in embeddings:
            values = getattr(item, "values", None) or []
            vectors.append([float(value) for value in values])
        self.active_backend = "gemini"
        return vectors

    def _embed_with_provider(self, texts: List[str]) -> List[List[float]]:
        errors: List[str] = []
        for provider in self._provider_candidates():
            if provider == "sentence_transformers":
                try:
                    return self._embed_with_sentence_transformers(texts)
                except Exception as exc:
                    errors.append(f"sentence_transformers={exc}")
                    continue
            if provider == "gemini":
                try:
                    return self._embed_with_gemini(texts)
                except Exception as exc:
                    errors.append(f"gemini={exc}")
                    continue
            if provider == "hash":
                self.active_backend = "hash_fallback"
                return [self._fallback_embedding(text) for text in texts]
        raise RuntimeError("; ".join(errors) or "No embedding provider available.")

    def backend_status(self) -> Dict[str, Any]:
        provider_candidates = self._provider_candidates()
        configured_provider = EMBEDDING_PROVIDER or (
            "external" if USE_EXTERNAL_EMBEDDING else "hash"
        )
        return {
            "provider": configured_provider,
            "backend": self.active_backend,
            "environment": ENVIRONMENT,
            "strict_mode": self.is_strict_mode_enabled(),
            "hash_fallback_allowed": not self.is_strict_mode_enabled(),
            "dimension": EMBEDDING_DIM,
            "sentence_transformer_model": SENTENCE_TRANSFORMER_MODEL,
            "gemini_embedding_model": GEMINI_EMBEDDING_MODEL,
            "candidate_order": provider_candidates,
            "vector_store_available": self.vector_store.available,
            "last_validation_error": self._last_validation_error,
        }

    def warmup(self) -> Dict[str, Any]:
        """Resolve the active embedding backend with a cheap warmup request."""
        self.embed_text("embedding warmup check")
        return self.backend_status()

    def validate_runtime(self, *, strict: Optional[bool] = None) -> Dict[str, Any]:
        """Validate embedding runtime and optionally hard-fail outside dev."""
        status = self.warmup()
        strict_mode = self.is_strict_mode_enabled() if strict is None else strict
        backend = str(status.get("backend") or "")
        if backend == "hash_fallback":
            message = (
                "Embedding backend resolved to hash_fallback. "
                "Set EMBEDDING_PROVIDER=sentence_transformers or gemini for demo/production."
            )
            self._last_validation_error = message
            status["last_validation_error"] = message
            if strict_mode:
                raise RuntimeError(message)
            logger.warning(message)
        else:
            self._last_validation_error = None
            status["last_validation_error"] = None
        return status

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
                try:
                    vectors = self._embed_with_provider(batch_texts)
                except Exception as exc:
                    logger.warning(
                        "Embedding provider failed, using local fallback: %s",
                        exc,
                    )
                    self.active_backend = "hash_fallback"
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
