"""Normalization helpers shared by recommendation services."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence, Set

try:
    from bson import ObjectId
except Exception:  # pragma: no cover - bson is available in the app runtime.
    ObjectId = None  # type: ignore


_RESOURCE_METADATA_KEYS = (
    "canonical_resource_key",
    "resource_identifier",
    "raw_resource_id",
    "mongo_id",
)

_CONCEPT_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("backend", "back end", "server side", "server-side", "api server"),
    ("api", "rest api", "restful api", "endpoint", "endpoints"),
    ("database", "db", "sql", "persistence", "data persistence"),
    ("authentication", "auth", "login", "sign in", "signin"),
    ("python", "py"),
    ("fastapi", "python api framework", "api framework"),
    ("http", "request response", "request/response", "web protocol"),
)

_BROAD_CONCEPT_TOKENS = {
    "data",
    "basic",
    "basics",
    "intro",
    "introduction",
    "overview",
    "course",
    "lesson",
    "learn",
    "study",
}


def normalize_resource_key(value: Any) -> str:
    """Return a stable string key for a resource identifier or document."""
    if isinstance(value, dict):
        if value.get("_id") is not None:
            return str(value.get("_id"))
        if value.get("mongo_id") is not None:
            return str(value.get("mongo_id"))
        if value.get("resource_id") is not None:
            return str(value.get("resource_id"))
        metadata = value.get("metadata") or {}
        for key in _RESOURCE_METADATA_KEYS:
            if metadata.get(key) is not None:
                return str(metadata.get(key))
        return ""
    if value is None:
        return ""
    return str(value).strip()


def extract_resource_keys(value: Any) -> Set[str]:
    """Return all known aliases for a resource so legacy ids still match."""
    keys: Set[str] = set()

    def add(raw: Any) -> None:
        text = normalize_resource_key(raw)
        if text:
            keys.add(text)

    if isinstance(value, dict):
        add(value.get("_id"))
        add(value.get("mongo_id"))
        add(value.get("resource_id"))
        metadata = value.get("metadata") or {}
        for key in _RESOURCE_METADATA_KEYS:
            add(metadata.get(key))
    else:
        add(value)
    return keys


def same_resource_key(left: Any, right: Any) -> bool:
    return bool(extract_resource_keys(left) & extract_resource_keys(right))


def normalize_concept_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9+#./-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIAS_LOOKUP: Dict[str, Set[str]] = {}
for group in _CONCEPT_ALIAS_GROUPS:
    normalized_group = {normalize_concept_text(item) for item in group if item}
    for alias in normalized_group:
        _ALIAS_LOOKUP[alias] = set(normalized_group)


def concept_aliases(value: Any) -> Set[str]:
    normalized = normalize_concept_text(value)
    if not normalized:
        return set()
    aliases = {normalized}
    aliases.update(_ALIAS_LOOKUP.get(normalized, set()))
    for key, group in _ALIAS_LOOKUP.items():
        if key in normalized or normalized in key:
            aliases.update(group)
    return {item for item in aliases if item}


def _concept_tokens(value: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9+#]+", normalize_concept_text(value))
        if len(token) >= 3 and token not in _BROAD_CONCEPT_TOKENS
    }


def concept_match_score(required: Sequence[Any], candidate_text: Any) -> float:
    required_terms = [normalize_concept_text(item) for item in required if normalize_concept_text(item)]
    if not required_terms:
        return 0.0
    haystack = normalize_concept_text(
        " ".join(str(item) for item in candidate_text)
        if isinstance(candidate_text, (list, tuple, set))
        else candidate_text
    )
    haystack_tokens = _concept_tokens(haystack)
    hits = 0.0
    for term in required_terms:
        aliases = concept_aliases(term)
        if any(alias and alias in haystack for alias in aliases):
            hits += 1.0
            continue
        term_tokens = _concept_tokens(term)
        if term_tokens and haystack_tokens:
            overlap = len(term_tokens & haystack_tokens) / max(len(term_tokens), 1)
            if overlap >= 0.6:
                hits += overlap
    return max(0.0, min(1.0, hits / max(len(required_terms), 1)))


def build_concept_match_context(
    required: Sequence[Any],
    candidate_text: Any,
) -> Dict[str, List[str] | float]:
    matched: List[str] = []
    unmatched: List[str] = []
    for term in required:
        normalized = normalize_concept_text(term)
        if not normalized:
            continue
        if concept_match_score([normalized], candidate_text) > 0.0:
            matched.append(normalized)
        else:
            unmatched.append(normalized)
    return {
        "matched_concepts": matched,
        "unmatched_concepts": unmatched,
        "concept_match_score": max(0.0, min(1.0, len(matched) / max(len(matched) + len(unmatched), 1))),
    }


def extract_goal_terms(goal: str) -> List[str]:
    raw_terms = re.findall(r"[a-zA-Z0-9+#./-]+", normalize_concept_text(goal))
    terms: List[str] = []
    seen: Set[str] = set()
    for term in raw_terms:
        if len(term) < 3 or term in _BROAD_CONCEPT_TOKENS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        for alias in sorted(concept_aliases(term)):
            if alias not in seen and len(alias) >= 3:
                seen.add(alias)
                terms.append(alias)
    return terms[:20]


def build_concept_match_context_from_terms(
    required: Iterable[Any],
    candidate_parts: Iterable[Any],
) -> Dict[str, List[str] | float]:
    return build_concept_match_context(list(required), " ".join(str(item) for item in candidate_parts if item))
