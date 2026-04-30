"""Helpers for suppressing URL/navigation-heavy chunks during question generation."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, Sequence

_URL_PATTERN = re.compile(r"https?://|www\.", flags=re.IGNORECASE)
_PATHISH_PATTERN = re.compile(
    r"\b(?:docs?\.[a-z0-9.-]+|[a-z0-9._-]+\.[a-z]{2,}(?:/[^\s]*)?)\b",
    flags=re.IGNORECASE,
)
_DOC_PATTERNS = (
    re.compile(r"\bdocumentation\b", flags=re.IGNORECASE),
    re.compile(r"\bapi reference\b", flags=re.IGNORECASE),
    re.compile(r"\bpython standard library\b", flags=re.IGNORECASE),
    re.compile(r"\breference manual\b", flags=re.IGNORECASE),
    re.compile(r"\bstandard library\b", flags=re.IGNORECASE),
    re.compile(r"\bmodule contents\b", flags=re.IGNORECASE),
)
_NAV_PATTERNS = (
    re.compile(r"\btable of contents\b", flags=re.IGNORECASE),
    re.compile(r"\bread more\b", flags=re.IGNORECASE),
    re.compile(r"\bprevious\b", flags=re.IGNORECASE),
    re.compile(r"\bnext\b", flags=re.IGNORECASE),
    re.compile(r"\bsearch\b", flags=re.IGNORECASE),
    re.compile(r"\bcontents\b", flags=re.IGNORECASE),
    re.compile(r"\bbreadcrumb\b", flags=re.IGNORECASE),
)
_COMMON_KEYWORD_STOPWORDS = {
    "about",
    "after",
    "also",
    "basic",
    "chapter",
    "course",
    "docs",
    "from",
    "guide",
    "have",
    "into",
    "lesson",
    "library",
    "more",
    "page",
    "python",
    "section",
    "source",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "what",
    "which",
}


def assess_question_generation_noise(
    *,
    content: Any,
    metadata: Dict[str, Any] | None = None,
    strict_keywords: Sequence[str] | None = None,
    broad_keywords: Sequence[str] | None = None,
    target_concepts: Sequence[str] | None = None,
    covered_concepts: Sequence[str] | None = None,
) -> Dict[str, Any]:
    raw_content = str(content or "")
    normalized_content = _normalize_text(raw_content)
    metadata_text = _normalize_text(_metadata_text(metadata))
    combined = " ".join(
        item for item in (metadata_text, normalized_content) if item
    ).strip()
    if not combined:
        return {
            "noise_score": 0.0,
            "relevance_score": 0.0,
            "resource_noise": False,
            "url_hits": 0,
            "doc_hits": 0,
            "navigation_hits": 0,
        }

    url_hits = len(_URL_PATTERN.findall(raw_content))
    pathish_hits = len(_PATHISH_PATTERN.findall(raw_content))
    doc_hits = sum(1 for pattern in _DOC_PATTERNS if pattern.search(combined))
    navigation_hits = sum(1 for pattern in _NAV_PATTERNS if pattern.search(combined))
    lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
    line_count = max(len(lines), 1)
    short_line_ratio = sum(1 for line in lines if len(line) <= 90) / line_count
    bullet_line_ratio = (
        sum(1 for line in lines if re.match(r"^(?:[-*]|[0-9]+\.)\s", line)) / line_count
    )
    sentence_count = len(re.findall(r"[.!?]", raw_content))
    token_count = max(len(re.findall(r"\b[a-z0-9_/-]+\b", combined)), 1)
    path_density = pathish_hits / token_count

    noise_score = 0.0
    if url_hits:
        noise_score += min(0.38 + url_hits * 0.18, 0.84)
    if pathish_hits >= 2:
        noise_score += min(0.14 * min(pathish_hits, 4), 0.42)
    if doc_hits:
        noise_score += min(0.12 * doc_hits + (0.12 if url_hits else 0.0), 0.5)
    if navigation_hits:
        noise_score += min(0.08 * navigation_hits, 0.24)
    if normalized_content.startswith(("http://", "https://", "www.")):
        noise_score += 0.22
    if sentence_count <= 1 and (url_hits or doc_hits):
        noise_score += 0.18
    if short_line_ratio >= 0.65:
        noise_score += 0.12
    if bullet_line_ratio >= 0.55:
        noise_score += 0.08
    if path_density >= 0.08:
        noise_score += 0.18
    if len(normalized_content) < 90 and (url_hits or doc_hits):
        noise_score += 0.12
    noise_score = round(min(noise_score, 1.0), 4)

    covered_text = " ".join(_iter_keywords(covered_concepts))
    strict_hits = _keyword_hit_count(combined, strict_keywords)
    broad_hits = _keyword_hit_count(combined, broad_keywords)
    target_hits = _keyword_hit_count(combined, target_concepts)
    covered_hits = _keyword_hit_count(covered_text, target_concepts)
    relevance_score = min(
        1.0,
        strict_hits * 0.34
        + broad_hits * 0.16
        + target_hits * 0.24
        + covered_hits * 0.18,
    )
    relevance_score = round(relevance_score, 4)

    resource_noise = bool(
        noise_score >= 0.86
        or (noise_score >= 0.58 and relevance_score < 0.36)
        or (
            noise_score >= 0.45
            and relevance_score <= 0.0
            and (url_hits > 0 or doc_hits > 0)
        )
    )

    return {
        "noise_score": noise_score,
        "relevance_score": relevance_score,
        "resource_noise": resource_noise,
        "url_hits": url_hits,
        "doc_hits": doc_hits,
        "navigation_hits": navigation_hits,
    }


def _metadata_text(metadata: Dict[str, Any] | None) -> str:
    metadata = metadata or {}
    values = [
        metadata.get("resource_title"),
        metadata.get("source_title"),
        metadata.get("title"),
        metadata.get("resource_source"),
        metadata.get("resource_url"),
        metadata.get("heading"),
        metadata.get("section_title"),
        metadata.get("chapter_title"),
    ]
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _iter_keywords(values: Sequence[str] | None) -> Iterable[str]:
    seen: set[str] = set()
    for value in values or []:
        normalized = _normalize_text(value)
        if (
            not normalized
            or normalized in seen
            or normalized in _COMMON_KEYWORD_STOPWORDS
        ):
            continue
        if len(normalized) < 4 and " " not in normalized:
            continue
        seen.add(normalized)
        yield normalized


def _keyword_hit_count(text: str, keywords: Sequence[str] | None) -> int:
    normalized_text = _normalize_text(text)
    hits = 0
    for keyword in _iter_keywords(keywords):
        pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
        if re.search(pattern, normalized_text):
            hits += 1
    return hits
