from __future__ import annotations

import re
from typing import List, Set


# =====================================================
# PSEUDOCODE
# =====================================================
# normalize_concept(text):
# 1. lowercase text
# 2. remove punctuation
# 3. split into tokens
# 4. remove stopwords
# 5. apply simple lemmatization rules
# 6. return normalized string
#
# detect_concept_type(text):
# 1. normalize concept
# 2. inspect rule keywords
# 3. classify into definition_concept / algorithm_concept /
#    application_concept / system_concept
#
# extract_keywords(text):
# 1. normalize concept
# 2. split into tokens
# 3. keep informative tokens only
# 4. return keyword list


STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "by",
    "is",
    "are",
    "la",
    "mot",
    "cac",
    "cua",
    "ve",
    "trong",
    "cho",
    "voi",
    "va",
    "nhung",
}

ALGORITHM_KEYWORDS = {
    "algorithm",
    "algorithms",
    "method",
    "methods",
    "technique",
    "techniques",
    "procedure",
    "procedure",
}

SYSTEM_KEYWORDS = {
    "system",
    "systems",
    "architecture",
    "architectures",
    "framework",
    "frameworks",
    "backend",
    "frontend",
}

APPLICATION_KEYWORDS = {
    "application",
    "applications",
    "use",
    "uses",
    "implementation",
    "implementations",
    "platform",
    "service",
    "services",
}


def _simple_lemmatize(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 3 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokenize(text: str) -> List[str]:
    clean_text = re.sub(r"[^a-zA-Z0-9\s]+", " ", (text or "").lower())
    return [token.strip() for token in clean_text.split() if token.strip()]


def normalize_concept(concept: str) -> str:
    tokens = [
        _simple_lemmatize(token)
        for token in _tokenize(concept)
        if token not in STOPWORDS
    ]
    return " ".join(tokens).strip()


def detect_concept_type(concept: str) -> str:
    normalized = normalize_concept(concept)
    tokens = set(normalized.split())

    if tokens & ALGORITHM_KEYWORDS:
        return "algorithm_concept"
    if tokens & SYSTEM_KEYWORDS:
        return "system_concept"
    if tokens & APPLICATION_KEYWORDS:
        return "application_concept"
    return "definition_concept"


def extract_keywords(concept: str) -> List[str]:
    normalized = normalize_concept(concept)
    return [token for token in normalized.split() if len(token) >= 3]
