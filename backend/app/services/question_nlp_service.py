"""Optional NLP helpers for question generation.

This service is designed to improve local deterministic generation without
making heavy dependencies mandatory. If optional libraries such as spaCy,
sentence-transformers, or rank-bm25 are unavailable, it falls back to a
lightweight TF-IDF and regex-based implementation.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from time import perf_counter
from typing import Dict, List, Optional, Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.app.utils.performance import add_timing

logger = logging.getLogger(__name__)


class QuestionNLPService:
    """Provide optional lexical and semantic helpers for fallback generation."""

    def __init__(self) -> None:
        self._spacy_nlp = self._load_spacy()
        self._sentence_transformer = self._load_sentence_transformer()
        self._bm25_class = self._load_bm25()

    @staticmethod
    def _load_spacy():
        try:
            import spacy

            for model_name in ("en_core_web_sm", "xx_ent_wiki_sm"):
                try:
                    return spacy.load(model_name)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    @staticmethod
    def _load_sentence_transformer():
        if os.getenv("QUESTION_NLP_USE_SENTENCE_TRANSFORMERS", "false").lower() != "true":
            return None
        try:
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            return None

    @staticmethod
    def _load_bm25():
        try:
            from rank_bm25 import BM25Okapi

            return BM25Okapi
        except Exception:
            return None

    def get_backend_status(self) -> dict:
        return {
            "spacy_available": self._spacy_nlp is not None,
            "sentence_transformers_available": self._sentence_transformer is not None,
            "rank_bm25_available": self._bm25_class is not None,
            "fallback_backend": "tfidf_regex",
        }

    def extract_keyphrases(self, text: str, *, top_k: int = 8) -> List[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        if self._spacy_nlp is not None:
            try:
                doc = self._spacy_nlp(text)
                phrases: List[str] = []
                seen: set[str] = set()
                for chunk in getattr(doc, "noun_chunks", []):
                    phrase = self._normalize_phrase(chunk.text)
                    if not phrase or phrase in seen:
                        continue
                    seen.add(phrase)
                    phrases.append(phrase)
                    if len(phrases) >= top_k:
                        return phrases
                for token in doc:
                    if not getattr(token, "is_alpha", False):
                        continue
                    if getattr(token, "is_stop", False):
                        continue
                    lemma = self._normalize_phrase(getattr(token, "lemma_", token.text))
                    if not lemma or lemma in seen:
                        continue
                    seen.add(lemma)
                    phrases.append(lemma)
                    if len(phrases) >= top_k:
                        break
                return phrases
            except Exception as exc:
                logger.debug("spaCy keyphrase extraction failed: %s", exc)

        tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", normalized)
        token_counts = Counter(token for token in tokens if len(token) >= 4)
        ranked = [token for token, _ in token_counts.most_common(top_k * 2)]
        phrases: List[str] = []
        seen: set[str] = set()
        for phrase in ranked:
            cleaned = self._normalize_phrase(phrase)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            phrases.append(cleaned)
            if len(phrases) >= top_k:
                break
        return phrases

    def semantic_similarity(
        self,
        text: str,
        targets: Sequence[str],
        *,
        timings: Optional[Dict[str, float]] = None,
    ) -> float:
        normalized_text = self._normalize_text(text)
        normalized_targets = [self._normalize_text(item) for item in targets if item]
        normalized_targets = [item for item in normalized_targets if item]
        if not normalized_text or not normalized_targets:
            return 0.0

        if self._sentence_transformer is not None:
            try:
                started_at = perf_counter()
                embeddings = self._sentence_transformer.encode(
                    [normalized_text, *normalized_targets],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                source = embeddings[0].reshape(1, -1)
                score = 0.0
                for target in embeddings[1:]:
                    similarity = float(cosine_similarity(source, target.reshape(1, -1))[0][0])
                    score = max(score, similarity)
                add_timing(timings, "sentence_transformers_embedding_ms", perf_counter() - started_at)
                return round(max(0.0, min(score, 1.0)), 4)
            except Exception as exc:
                logger.debug("SentenceTransformer similarity failed: %s", exc)

        return self.tfidf_similarity(normalized_text, normalized_targets)

    def lexical_relevance(
        self,
        text: str,
        targets: Sequence[str],
        *,
        timings: Optional[Dict[str, float]] = None,
    ) -> float:
        normalized_text = self._normalize_text(text)
        normalized_targets = [self._normalize_text(item) for item in targets if item]
        normalized_targets = [item for item in normalized_targets if item]
        if not normalized_text or not normalized_targets:
            return 0.0

        if self._bm25_class is not None:
            try:
                started_at = perf_counter()
                corpus = [
                    re.findall(r"\w+", normalized_text),
                    *[re.findall(r"\w+", target) for target in normalized_targets],
                ]
                bm25 = self._bm25_class(corpus)
                query_tokens = [token for target in normalized_targets for token in re.findall(r"\w+", target)]
                scores = bm25.get_scores(query_tokens)
                score = float(scores[0]) if len(scores) else 0.0
                add_timing(timings, "bm25_retrieval_ms", perf_counter() - started_at)
                return round(max(0.0, math.tanh(score / 6.0)), 4)
            except Exception as exc:
                logger.debug("BM25 lexical relevance failed: %s", exc)

        return self.tfidf_similarity(normalized_text, normalized_targets)

    def tfidf_similarity(self, text: str, targets: Sequence[str]) -> float:
        documents = [self._normalize_text(text), *[self._normalize_text(item) for item in targets if item]]
        documents = [item for item in documents if item]
        if len(documents) < 2:
            return 0.0
        try:
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            matrix = vectorizer.fit_transform(documents)
            source = matrix[0]
            score = 0.0
            for index in range(1, matrix.shape[0]):
                similarity = float(cosine_similarity(source, matrix[index])[0][0])
                score = max(score, similarity)
            return round(max(0.0, min(score, 1.0)), 4)
        except Exception as exc:
            logger.debug("TF-IDF similarity failed: %s", exc)
            return 0.0

    def keyword_overlap_terms(self, text: str, targets: Sequence[str], *, top_k: int = 5) -> List[str]:
        text_phrases = self.extract_keyphrases(text, top_k=max(top_k * 2, 8))
        normalized_targets = [self._normalize_phrase(item) for item in targets if item]
        normalized_targets = [item for item in normalized_targets if item]
        if not text_phrases or not normalized_targets:
            return []

        overlaps: List[str] = []
        seen: set[str] = set()
        for phrase in text_phrases:
            if any(target in phrase or phrase in target for target in normalized_targets):
                if phrase not in seen:
                    seen.add(phrase)
                    overlaps.append(phrase)
            if len(overlaps) >= top_k:
                break
        return overlaps

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").strip().lower().split())

    @classmethod
    def _normalize_phrase(cls, text: str) -> str:
        value = cls._normalize_text(text)
        if not value:
            return ""
        if len(value) < 3:
            return ""
        return value


question_nlp_service = QuestionNLPService()
