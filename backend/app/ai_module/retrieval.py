"""Semantic retrieval over chunk collection."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from backend.app.ai_module.embedding import cosine_similarity, embedding_service
from backend.app.repositories import ResourceChunkRepository, ResourceRepository

logger = logging.getLogger(__name__)


class SemanticRetrievalService:
    """Retrieve top-k chunks and hydrate parent resources."""

    def __init__(self) -> None:
        self.embedding_service = embedding_service
        self.chunk_repository = ResourceChunkRepository()
        self.resource_repository = ResourceRepository()

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float = 0.35,
        topic: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return best matching chunks grouped by parent resource."""
        query_embedding = self.embedding_service.embed_text(query)

        where: Dict[str, Any] = {}
        if topic:
            where["topic"] = topic
        if level:
            where["level"] = level

        vector_hits = self.embedding_service.vector_store.query(
            query_embedding,
            limit=max(k * 3, 10),
            where=where or None,
        )

        if vector_hits:
            candidates = []
            for hit in vector_hits:
                metadata = hit.get("metadata") or {}
                candidates.append(
                    {
                        "resource_id": metadata.get("resource_id"),
                        "chunk_index": metadata.get("chunk_index"),
                        "content": hit.get("content", ""),
                        "score": round(
                            max(0.0, 1.0 - float(hit.get("distance", 1.0))), 4
                        ),
                    }
                )
        else:
            candidates = self._search_mongo_candidates(
                query_embedding=np.array(query_embedding, dtype=float),
                k=max(k * 20, 100),
                min_score=min_score,
                topic=topic,
                level=level,
            )

        grouped: Dict[str, Dict[str, Any]] = {}
        for candidate in candidates:
            score = float(candidate.get("score", 0.0))
            if score < min_score:
                continue
            resource_id = str(candidate["resource_id"])
            resource = grouped.get(resource_id)
            if resource is None or score > resource["score"]:
                parent = self.resource_repository.get(resource_id)
                if not parent:
                    continue
                grouped[resource_id] = {
                    "resource_id": resource_id,
                    "title": parent.get("title"),
                    "topic": parent.get("topic"),
                    "level": parent.get("metadata", {}).get("level"),
                    "source": parent.get("source"),
                    "type": parent.get("type"),
                    "score": round(score, 4),
                    "snippet": candidate.get("content", "")[:600],
                    "matched_chunk": candidate.get("chunk_index"),
                    "metadata": parent.get("metadata", {}),
                    "content_summary": parent.get("content_summary"),
                }

        results = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)
        return results[:k]

    def _search_mongo_candidates(
        self,
        *,
        query_embedding: np.ndarray,
        k: int,
        min_score: float,
        topic: Optional[str],
        level: Optional[str],
    ) -> List[Dict[str, Any]]:
        candidates = self.chunk_repository.candidate_chunks(
            topic=topic, level=level, limit=max(k, 100)
        )
        scored: List[Dict[str, Any]] = []
        for chunk in candidates:
            embedding = np.array(chunk.get("embedding") or [], dtype=float)
            if embedding.size == 0:
                continue
            score = cosine_similarity(query_embedding, embedding)
            if score < min_score:
                continue
            scored.append({**chunk, "score": round(score, 4)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]
