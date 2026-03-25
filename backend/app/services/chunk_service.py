"""Chunking and text-cleaning utilities for ingestion."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_CHUNK_SIZE = int(os.getenv("RESOURCE_CHUNK_SIZE", "1200"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("RESOURCE_CHUNK_OVERLAP", "180"))
DEFAULT_MIN_CHUNK_LENGTH = int(os.getenv("RESOURCE_MIN_CHUNK_LENGTH", "80"))


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_length: int = DEFAULT_MIN_CHUNK_LENGTH,
) -> List[str]:
    """Split text into overlapping chunks along sentence-like boundaries."""
    normalized = clean_text(text)
    if not normalized:
        return []

    if len(normalized) <= chunk_size:
        return [normalized] if len(normalized) >= min_length else []

    chunks: List[str] = []
    start = 0
    text_length = len(normalized)
    step = max(1, chunk_size - overlap)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            boundary = max(
                normalized.rfind(". ", start, end),
                normalized.rfind("? ", start, end),
                normalized.rfind("! ", start, end),
                normalized.rfind("\n\n", start, end),
                normalized.rfind("\n", start, end),
            )
            if boundary > start + int(chunk_size * 0.5):
                end = boundary + 1

        chunk = normalized[start:end].strip()
        if len(chunk) >= min_length:
            chunks.append(chunk)

        if end >= text_length:
            break
        start = max(end - overlap, start + step)

    return chunks


def build_chunk_documents(
    *,
    resource_id: Any,
    chunks: List[str],
    embeddings: List[List[float]],
    metadata: Dict[str, object],
    chunk_indexes: Optional[List[int]] = None,
    chunk_metadata_overrides: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """Create chunk documents for MongoDB insertion."""
    if chunk_indexes is not None and len(chunk_indexes) != len(chunks):
        raise ValueError("chunk_indexes length must match chunks length.")
    if chunk_metadata_overrides is not None and len(chunk_metadata_overrides) != len(chunks):
        raise ValueError("chunk_metadata_overrides length must match chunks length.")

    documents: List[Dict[str, object]] = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        document_index = chunk_indexes[index] if chunk_indexes is not None else index
        per_chunk_metadata = chunk_metadata_overrides[index] if chunk_metadata_overrides is not None else {}
        documents.append(
            {
                "resource_id": resource_id,
                "chunk_index": document_index,
                "content": chunk,
                "embedding": embedding,
                "metadata": {**metadata, **per_chunk_metadata, "chunk_size": len(chunk)},
            }
        )
    return documents
