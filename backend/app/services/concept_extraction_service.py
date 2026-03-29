"""Extract learning concepts from chunks/questions using lightweight heuristics."""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence


class ConceptExtractionService:
    """Detect core programming concepts from text snippets."""

    _CONCEPT_PATTERNS = {
        "variables": [r"\bvariable(s)?\b", r"\bassignment\b", r"\bidentifier\b"],
        "loops": [r"\bfor\b", r"\bwhile\b", r"\bloop(s)?\b", r"\biterate\b"],
        "functions": [r"\bfunction(s)?\b", r"\bdef\b", r"\breturn\b", r"\bparameter(s)?\b"],
        "classes": [r"\bclass(es)?\b", r"\bobject(s)?\b", r"\bmethod(s)?\b", r"\bconstructor\b"],
        "conditions": [r"\bif\b", r"\belif\b", r"\belse\b", r"\bcondition(al)?\b"],
        "lists": [r"\blist(s)?\b", r"\barray(s)?\b", r"\bindex\b", r"\bslice\b"],
        "dictionaries": [r"\bdict(ionary)?\b", r"\bkey(s)?\b", r"\bvalue(s)?\b", r"\bmap\b"],
        "errors": [r"\berror(s)?\b", r"\bexception(s)?\b", r"\btry\b", r"\bexcept\b"],
    }

    _STOPWORDS = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "your",
        "have",
        "using",
        "code",
        "lesson",
    }

    def extract_from_chunks(self, chunks: Sequence[dict]) -> List[str]:
        text_payload: List[str] = []
        for chunk in chunks or []:
            text_payload.append(str(chunk.get("content") or ""))
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            text_payload.append(str(metadata.get("title") or ""))
            text_payload.append(str(metadata.get("summary") or ""))
        return self.extract_from_texts(text_payload)

    def extract_from_texts(self, texts: Iterable[str], max_concepts: int = 5) -> List[str]:
        normalized_text = "\n".join(self._normalize(text) for text in texts if text)
        if not normalized_text.strip():
            return []

        detected: List[str] = []
        for concept, patterns in self._CONCEPT_PATTERNS.items():
            if any(re.search(pattern, normalized_text, flags=re.IGNORECASE) for pattern in patterns):
                detected.append(concept)

        if len(detected) >= max_concepts:
            return detected[:max_concepts]

        # Lightweight keyword extraction fallback.
        tokens = re.findall(r"\b[a-z][a-z0-9_]{3,}\b", normalized_text)
        ranked: List[str] = []
        seen: set[str] = set(detected)
        for token in tokens:
            if token in self._STOPWORDS or token in seen:
                continue
            seen.add(token)
            ranked.append(token)
            if len(detected) + len(ranked) >= max_concepts:
                break

        return [*detected, *ranked][:max_concepts]

    def detect_question_concept(self, *, question_text: str, chunk_text: str = "") -> str:
        candidates = self.extract_from_texts([question_text, chunk_text], max_concepts=1)
        return candidates[0] if candidates else "general"

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").lower()).strip()


concept_extraction_service = ConceptExtractionService()
