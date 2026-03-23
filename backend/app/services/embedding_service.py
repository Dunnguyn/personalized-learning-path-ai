"""Backward-compatible embedding and retrieval facade."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.ai_module import EmbeddingService, SemanticRetrievalService, cosine_similarity
from backend.app.repositories import ResourceChunkRepository, ResourceRepository
from backend.app.services.chunk_service import build_chunk_documents, clean_text, split_into_chunks

_embedding_service = EmbeddingService()
# Backward-compatible public alias used by existing service imports.
embedding_service = _embedding_service
_retrieval_service = SemanticRetrievalService()
_resource_repository = ResourceRepository()
_chunk_repository = ResourceChunkRepository()


def embed_text(text: str) -> List[float]:
    """Embed a single text."""
    return _embedding_service.embed_text(text)


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
    pdf_file_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Store a resource and its chunks using the unified schema."""
    normalized = clean_text(content or title)
    resource_type = "text" if source not in {"pdf", "youtube"} else source
    resource = _resource_repository.create(
        {
            "title": title,
            "type": resource_type,
            "topic": topic,
            "source": source,
            "content_summary": normalized[:800],
            "status": "done",
            "chunks_count": 0,
            "processing_time": 0.0,
            "metadata": {
                "level": level,
                "concept_id": concept_id,
                "url": url,
                "pedagogy_type": pedagogy_type,
                "bloom_level": bloom_level,
                "thumbnail": thumbnail,
                "pdf_file_path": pdf_file_path,
            },
        }
    )

    chunks = split_into_chunks(normalized) or [normalized]
    embeddings = _embedding_service.embed_texts(chunks)
    documents = build_chunk_documents(
        resource_id=resource["_id"],
        chunks=chunks,
        embeddings=embeddings,
        metadata={
            "topic": topic,
            "level": level,
            "source": source,
            "resource_type": resource_type,
            "pedagogy_type": pedagogy_type,
            "bloom_level": bloom_level,
            "thumbnail": thumbnail,
        },
    )
    inserted_count = _chunk_repository.insert_many(documents)
    vector_records = [
        {
            "id": f"{resource['_id']}:{document['chunk_index']}",
            "embedding": document["embedding"],
            "content": document["content"],
            "metadata": {
                "topic": str(document["metadata"].get("topic") or ""),
                "level": str(document["metadata"].get("level") or ""),
                "resource_id": str(resource["_id"]),
                "chunk_index": document["chunk_index"],
            },
        }
        for document in documents
    ]
    _embedding_service.vector_store.upsert_chunks(vector_records)
    updated = _resource_repository.update(
        resource["_id"],
        {"chunks_count": inserted_count, "status": "done", "processing_time": 0.0},
    )
    serialized = updated or resource
    serialized["resource_id"] = str(serialized["_id"])
    return serialized


def store_embedding_only(
    content: str,
    parent_resource_id: str,
    chunk_index: int,
    topic: str,
    level: str = "beginner",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Store only a chunk document for an existing resource."""
    embedding = _embedding_service.embed_text(content)
    document = {
        "resource_id": ObjectId(parent_resource_id),
        "chunk_index": chunk_index,
        "content": clean_text(content),
        "embedding": embedding,
        "metadata": {
            "topic": topic,
            "level": level,
            **(metadata or {}),
        },
        "created_at": datetime.utcnow(),
    }
    inserted = _chunk_repository.collection.insert_one(document)
    _embedding_service.vector_store.upsert_chunks(
        [
            {
                "id": f"{parent_resource_id}:{chunk_index}",
                "embedding": embedding,
                "content": document["content"],
                "metadata": {
                    "topic": topic,
                    "level": level,
                    "resource_id": parent_resource_id,
                    "chunk_index": chunk_index,
                },
            }
        ]
    )
    _resource_repository.update(
        parent_resource_id,
        {"chunks_count": _chunk_repository.count_for_resource(parent_resource_id), "status": "done"},
    )
    return str(inserted.inserted_id)


def store_resources_batch(resources: List[Dict[str, Any]]) -> Dict[str, int]:
    """Store multiple text-like resources."""
    inserted = 0
    failed = 0
    for resource in resources:
        try:
            store_resource(
                title=resource.get("title", ""),
                content=resource.get("content", ""),
                topic=resource.get("topic", ""),
                level=resource.get("level", "beginner"),
                source=resource.get("source", "manual"),
                concept_id=resource.get("concept_id"),
                url=resource.get("url"),
                pedagogy_type=resource.get("pedagogy_type"),
                bloom_level=resource.get("bloom_level"),
            )
            inserted += 1
        except Exception:
            failed += 1
    return {"inserted_count": inserted, "failed_count": failed}


def semantic_search(
    query: str,
    k: int = 5,
    min_score: float = 0.35,
    topic: Optional[str] = None,
    level: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Semantic search over unified chunk storage."""
    return _retrieval_service.search(
        query=query,
        k=k,
        min_score=min_score,
        topic=topic,
        level=level,
    )
