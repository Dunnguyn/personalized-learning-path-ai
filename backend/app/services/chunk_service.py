"""Chunking and text-cleaning utilities for ingestion."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_CHUNK_SIZE = int(os.getenv("RESOURCE_CHUNK_SIZE", "1200"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("RESOURCE_CHUNK_OVERLAP", "180"))
DEFAULT_MIN_CHUNK_LENGTH = int(os.getenv("RESOURCE_MIN_CHUNK_LENGTH", "80"))
DEFAULT_CHUNK_KEYWORD_LIMIT = int(os.getenv("RESOURCE_CHUNK_KEYWORD_LIMIT", "8"))
DEFAULT_CHUNKING_STRATEGY = os.getenv("RESOURCE_CHUNKING_STRATEGY", "semantic").strip().lower()

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "then",
    "than",
    "when",
    "where",
    "which",
    "while",
    "will",
    "using",
    "use",
    "used",
    "your",
    "you",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "can",
    "could",
    "should",
    "would",
    "about",
    "there",
    "them",
    "they",
    "their",
    "what",
    "why",
    "how",
    "let",
    "lets",
    "also",
    "more",
    "most",
    "very",
    "much",
    "many",
    "some",
    "such",
    "each",
    "through",
    "because",
    "over",
    "than",
    "into",
    "onto",
    "under",
    "gi",
    "la",
    "hoc",
    "bai",
    "chuong",
    "phan",
    "mot",
    "nhung",
    "cac",
    "cho",
    "khi",
    "neu",
    "voi",
    "trong",
    "tren",
    "duoc",
    "hay",
    "lam",
    "sau",
    "truoc",
    "nay",
    "kia",
    "moi",
    "cua",
    "nhu",
    "theo",
    "phan",
    "noi",
    "dung",
}
_INDEX_LINE_PATTERN = re.compile(
    r"^[^\n]{2,120}?(?:,|\.)?\s+\d{1,4}(?:-\d{1,4})?\s*$"
)


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_heading_candidate(text: str) -> bool:
    compact = clean_text(text)
    if not compact:
        return False
    if len(compact) > 120:
        return False
    if re.match(r"^(chapter|section|lesson|part)\b", compact, flags=re.IGNORECASE):
        return True
    if re.match(r"^\d+(?:\.\d+)*\s+[A-Za-z0-9]", compact):
        return True
    if compact.endswith((".", "?", "!", ";", ":")):
        return False
    words = compact.split()
    return 1 <= len(words) <= 10


def semantic_chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    min_length: int = DEFAULT_MIN_CHUNK_LENGTH,
) -> List[Dict[str, Any]]:
    """Split text by paragraphs/headings and attach section metadata."""
    normalized = clean_text(text)
    if not normalized:
        return []

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n+", normalized)
        if paragraph and paragraph.strip()
    ]
    if not paragraphs:
        return []

    chunk_entries: List[Dict[str, Any]] = []
    current_parts: List[str] = []
    current_heading = ""
    current_section_index = 0
    current_paragraph_count = 0

    def flush_chunk() -> None:
        nonlocal current_parts, current_paragraph_count
        chunk_text = "\n\n".join(part for part in current_parts if part).strip()
        effective_min_length = min_length
        if current_heading:
            effective_min_length = max(20, min_length // 3)
        if len(chunk_text) < effective_min_length:
            return
        chunk_entries.append(
            {
                "text": chunk_text,
                "metadata": {
                    "heading": current_heading,
                    "section_title": current_heading,
                    "semantic_section_index": current_section_index,
                    "paragraph_count": current_paragraph_count,
                    "chunking_strategy": "semantic",
                },
            }
        )
        current_parts = []
        current_paragraph_count = 0

    for paragraph in paragraphs:
        if _is_heading_candidate(paragraph):
            if current_parts:
                flush_chunk()
            current_heading = paragraph
            current_section_index += 1
            continue

        if (
            current_parts
            and len("\n\n".join([*current_parts, paragraph])) > chunk_size
        ):
            flush_chunk()

        if len(paragraph) > chunk_size and not current_parts:
            for partial in split_into_chunks(
                paragraph,
                chunk_size=chunk_size,
                overlap=0,
                min_length=min_length,
                strategy="fixed",
            ):
                chunk_entries.append(
                    {
                        "text": partial,
                        "metadata": {
                            "heading": current_heading,
                            "section_title": current_heading,
                            "semantic_section_index": current_section_index,
                            "paragraph_count": 1,
                            "chunking_strategy": "semantic",
                        },
                    }
                )
            continue

        current_parts.append(paragraph)
        current_paragraph_count += 1

    if current_parts:
        flush_chunk()

    return chunk_entries


def split_into_chunks(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_length: int = DEFAULT_MIN_CHUNK_LENGTH,
    strategy: str = DEFAULT_CHUNKING_STRATEGY,
) -> List[str]:
    """Split text into overlapping chunks along sentence-like boundaries."""
    normalized = clean_text(text)
    if not normalized:
        return []

    if strategy == "semantic":
        semantic_chunks = semantic_chunk_text(
            normalized,
            chunk_size=chunk_size,
            min_length=min_length,
        )
        if semantic_chunks:
            return [str(item["text"]) for item in semantic_chunks if item.get("text")]

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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _tokenize(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"\w+", _normalize_text(text))
        if len(token) >= 3
    ]


def _sentence_like_segments(text: str) -> List[str]:
    compact = clean_text(text)
    if not compact:
        return []
    segments = re.split(r"(?<=[.!?])\s+|\n+", compact)
    return [segment.strip() for segment in segments if segment.strip()]


def _first_meaningful_sentence(text: str, max_chars: int = 180) -> str:
    for segment in _sentence_like_segments(text):
        normalized = _normalize_text(segment)
        if len(normalized) < 20:
            continue
        if _INDEX_LINE_PATTERN.match(segment.strip()):
            continue
        return segment[:max_chars].strip()
    return clean_text(text)[:max_chars].strip()


def _infer_instruction_role(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "explanation"
    if "table of contents" in normalized or normalized.startswith("contents "):
        return "reference"
    if any(
        marker in normalized
        for marker in (
            "for example",
            "example",
            "vi du",
            "ví dụ",
            "sample output",
            "walkthrough",
            "@",
        )
    ):
        return "worked_example"
    if any(
        marker in normalized
        for marker in (
            "in summary",
            "summary",
            "tong ket",
            "tổng kết",
            "key takeaways",
        )
    ):
        return "summary"
    if any(
        marker in normalized
        for marker in (
            "is ",
            "are ",
            "means ",
            "defined as",
            "refers to",
            "la ",
            "là ",
        )
    ):
        return "definition"
    if any(
        marker in normalized
        for marker in (
            "step 1",
            "step 2",
            "first,",
            "next,",
            "finally",
            "how to",
        )
    ):
        return "procedure"
    return "explanation"


def _infer_content_kind(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "empty"
    if (
        "table of contents" in normalized
        or "glossary" in normalized
        or "bibliography" in normalized
    ):
        return "structural"
    if _infer_instruction_role(text) == "worked_example":
        return "example"
    if _infer_instruction_role(text) == "definition":
        return "definition"
    if "```" in text or re.search(r"\bfor\b.*:|\bwhile\b.*:|=>|:=|{.+}", text):
        return "code"
    return "concept"


def _questionability_score(text: str, instruction_role: str) -> float:
    normalized = _normalize_text(text)
    sentences = _sentence_like_segments(text)
    numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text or "")
    list_markers = re.findall(r"^\s*(?:[-*]|\d+\.)\s+", text or "", flags=re.MULTILINE)
    definition_hits = len(
        re.findall(r"\b(is|are|means|defined as|refers to|la|là)\b", normalized)
    )
    has_code = "```" in text or bool(re.search(r"\bfor\b.*:|\bwhile\b.*:|=>|:=|{.+}", text))
    role_bonus = {
        "worked_example": 0.12,
        "definition": 0.10,
        "summary": 0.04,
        "procedure": 0.08,
        "explanation": 0.06,
    }.get(instruction_role, 0.0)
    score = (
        min(len(sentences) / 6.0, 1.0) * 0.35
        + min(len(numbers) / 4.0, 1.0) * 0.15
        + min((definition_hits + len(list_markers)) / 4.0, 1.0) * 0.25
        + float(has_code) * 0.15
        + role_bonus
    )
    return round(min(max(score, 0.0), 1.0), 4)


def _extract_keywords(text: str, metadata: Optional[Dict[str, Any]] = None) -> List[str]:
    tokens = _tokenize(text)
    if not tokens:
        return []
    metadata = metadata or {}
    excluded = set(_STOP_WORDS)
    excluded.update(_tokenize(str(metadata.get("topic") or "")))
    excluded.update(_tokenize(str(metadata.get("level") or "")))
    scores: Dict[str, float] = {}
    for index, token in enumerate(tokens):
        if token in excluded:
            continue
        weight = 1.0
        if index < 20:
            weight += 0.35
        if len(token) >= 8:
            weight += 0.1
        scores[token] = scores.get(token, 0.0) + weight
    ranked = sorted(scores.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [token for token, _ in ranked[:DEFAULT_CHUNK_KEYWORD_LIMIT]]


def derive_chunk_metadata(
    text: str,
    *,
    base_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    """Derive lightweight semantic metadata for a chunk."""
    cleaned = clean_text(text)
    instruction_role = _infer_instruction_role(cleaned)
    keywords = _extract_keywords(cleaned, metadata=base_metadata)
    content_kind = _infer_content_kind(cleaned)
    summary = _first_meaningful_sentence(cleaned)
    sentences = _sentence_like_segments(cleaned)
    token_count = len(_tokenize(cleaned))
    covered_concepts = keywords[: min(len(keywords), 6)]
    semantic_density = round(min(len(set(keywords)) / max(token_count / 30.0, 1.0), 1.0), 4)
    level_hint = "beginner"
    if token_count >= 160 or content_kind == "code":
        level_hint = "intermediate"
    if token_count >= 280 or (
        content_kind == "code" and instruction_role == "worked_example"
    ):
        level_hint = "advanced"
    return {
        "chunk_summary": summary,
        "chunk_keywords": keywords,
        "covered_concepts": covered_concepts,
        "instruction_role": instruction_role,
        "content_kind": content_kind,
        "questionability_score": _questionability_score(cleaned, instruction_role),
        "token_count": token_count,
        "sentence_count": len(sentences),
        "semantic_density": semantic_density,
        "level_hint": level_hint,
        "has_code": content_kind == "code" or instruction_role == "worked_example",
    }


def aggregate_chunk_profile(chunks: List[Dict[str, Any]]) -> Dict[str, object]:
    """Aggregate resource-level chunk profile from stored chunk documents."""
    keyword_counts: Dict[str, int] = {}
    concept_counts: Dict[str, int] = {}
    role_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    level_counts: Dict[str, int] = {}
    semantic_density_values: List[float] = []

    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        for keyword in metadata.get("chunk_keywords", []) or []:
            token = str(keyword or "").strip().lower()
            if not token:
                continue
            keyword_counts[token] = keyword_counts.get(token, 0) + 1
        for concept in metadata.get("covered_concepts", []) or []:
            token = str(concept or "").strip().lower()
            if not token:
                continue
            concept_counts[token] = concept_counts.get(token, 0) + 1
        role = str(metadata.get("instruction_role") or "").strip().lower()
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
        kind = str(metadata.get("content_kind") or "").strip().lower()
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        level_hint = str(metadata.get("level_hint") or "").strip().lower()
        if level_hint:
            level_counts[level_hint] = level_counts.get(level_hint, 0) + 1
        try:
            semantic_density_values.append(float(metadata.get("semantic_density") or 0.0))
        except Exception:
            continue

    top_keywords = [
        keyword
        for keyword, _ in sorted(
            keyword_counts.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0]),
        )[:12]
    ]
    top_concepts = [
        concept
        for concept, _ in sorted(
            concept_counts.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0]),
        )[:10]
    ]
    return {
        "top_keywords": top_keywords,
        "top_concepts": top_concepts,
        "covered_concepts": top_concepts,
        "instruction_roles": role_counts,
        "content_kinds": kind_counts,
        "level_hints": level_counts,
        "avg_semantic_density": round(
            sum(semantic_density_values) / max(len(semantic_density_values), 1), 4
        ),
    }


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
    if chunk_metadata_overrides is not None and len(chunk_metadata_overrides) != len(
        chunks
    ):
        raise ValueError("chunk_metadata_overrides length must match chunks length.")

    documents: List[Dict[str, object]] = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        document_index = chunk_indexes[index] if chunk_indexes is not None else index
        per_chunk_metadata = (
            chunk_metadata_overrides[index]
            if chunk_metadata_overrides is not None
            else {}
        )
        derived_metadata = derive_chunk_metadata(chunk, base_metadata=metadata)
        documents.append(
            {
                "resource_id": resource_id,
                "chunk_index": document_index,
                "content": chunk,
                "embedding": embedding,
                "metadata": {
                    **metadata,
                    **derived_metadata,
                    **per_chunk_metadata,
                    "chunk_size": len(chunk),
                },
            }
        )
    return documents
