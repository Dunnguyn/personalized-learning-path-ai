"""Build bilingual lesson queries from Vietnamese learning descriptions."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Sequence

from backend.app.utils.gemini import get_gemini_client

logger = logging.getLogger(__name__)


def _lesson_query_quota_cooldown_seconds(error: Exception) -> int | None:
    text = str(error)
    if "RESOURCE_EXHAUSTED" not in text and "Quota exceeded" not in text and "429" not in text:
        return None
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", text, re.IGNORECASE)
    if not match:
        match = re.search(r"retryDelay': '([0-9]+)s'", text)
    if match:
        return int(float(match.group(1)))
    return None


class LessonSemanticQueryService:
    """Expand lesson descriptions into bilingual Vietnamese-English search intent."""

    _PHRASE_TRANSLATIONS: Dict[str, List[str]] = {
        "lap trinh huong doi tuong": ["object oriented programming", "oop"],
        "xu ly ngoai le": ["exception handling", "exceptions"],
        "vong lap for": ["for loop", "for statement", "iteration"],
        "vong lap while": ["while loop", "while statement", "iteration"],
        "vong lap": ["loop", "iteration"],
        "cau lenh if else": ["if else", "conditional statement", "branching"],
        "cau lenh if": ["if statement", "conditional statement"],
        "cau lenh else": ["else branch", "conditional statement"],
        "dieu kien": ["condition", "conditional logic"],
        "ham lambda": ["lambda function", "anonymous function"],
        "ham": ["function"],
        "phuong thuc": ["method"],
        "tham so": ["parameter"],
        "doi so": ["argument"],
        "gia tri tra ve": ["return value"],
        "de quy": ["recursion", "recursive function"],
        "danh sach": ["list", "sequence"],
        "tu dien": ["dictionary", "mapping"],
        "chuoi": ["string", "text"],
        "so nguyen": ["integer", "int"],
        "so thuc": ["float", "floating point"],
        "tep": ["file"],
        "tap tin": ["file"],
        "doc file": ["read file", "file input"],
        "ghi file": ["write file", "file output"],
        "bat dong bo": ["asynchronous", "async"],
        "dong bo": ["synchronous", "sync"],
        "trinh tao": ["generator"],
        "bo sinh": ["generator"],
        "trang tri": ["decorator"],
        "bo trang tri": ["decorator"],
        "quan ly ngu canh": ["context manager"],
        "mang": ["array", "list"],
        "lop": ["class"],
        "doi tuong": ["object", "instance"],
        "ke thua": ["inheritance"],
        "dong goi": ["encapsulation"],
        "da hinh": ["polymorphism"],
        "thuat toan": ["algorithm"],
        "cau truc du lieu": ["data structure"],
        "sap xep": ["sorting", "sort algorithm"],
        "tim kiem": ["search", "search algorithm"],
        "tong quan": ["overview"],
        "gioi thieu": ["introduction", "overview"],
        "co ban": ["basics", "fundamentals"],
        "nang cao": ["advanced"],
        "khai niem": ["concept"],
        "vi du": ["example"],
        "thuc hanh": ["practice", "hands on"],
    }
    _ACTION_TRANSLATIONS: Dict[str, List[str]] = {
        "hieu": ["understand"],
        "giai thich": ["explain"],
        "su dung": ["use", "usage"],
        "ap dung": ["apply"],
        "phan biet": ["distinguish", "compare"],
        "trien khai": ["implement"],
        "viet": ["write"],
        "tao": ["create", "build"],
        "phan tich": ["analyze"],
        "toi uu": ["optimize"],
    }
    _KEEP_TOKENS = {
        "python",
        "java",
        "javascript",
        "typescript",
        "react",
        "fastapi",
        "django",
        "flask",
        "numpy",
        "pandas",
        "sql",
        "html",
        "css",
        "api",
        "oop",
        "asyncio",
        "decorator",
        "decorators",
        "generator",
        "generators",
        "iterator",
        "iterators",
        "recursion",
        "lambda",
    }
    _STOP_WORDS = {
        "bai",
        "hoc",
        "chuong",
        "lesson",
        "chapter",
        "subject",
        "va",
        "voi",
        "trong",
        "tren",
        "duoi",
        "cua",
        "cho",
        "mot",
        "nhung",
        "cac",
        "nay",
        "kia",
        "moi",
    }
    _LLM_MODEL = os.getenv(
        "LESSON_QUERY_LLM_MODEL",
        os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
    )
    _LLM_MAX_RETRIES = int(os.getenv("LESSON_QUERY_LLM_MAX_RETRIES", "1"))
    _LLM_COOLDOWN_SECONDS = int(os.getenv("LESSON_QUERY_LLM_COOLDOWN_SECONDS", "300"))
    _LLM_ENABLED = (
        os.getenv("LESSON_QUERY_LLM_ENABLED", "true").lower() == "true"
    )

    def __init__(self) -> None:
        self.client = self._init_client()
        self._llm_cooldown_until = 0.0

    def _init_client(self):
        if not self._LLM_ENABLED:
            return None
        try:
            return get_gemini_client()
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Lesson semantic query Gemini client unavailable: %s", exc)
            return None

    @staticmethod
    def _strip_accents(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @classmethod
    def _normalize_for_match(cls, value: str) -> str:
        lowered = cls._strip_accents(value).lower()
        lowered = lowered.replace("đ", "d").replace("Ð", "d")
        lowered = re.sub(r"[^a-z0-9_+\-#/ ]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    @staticmethod
    def _clean_phrase(value: str) -> str:
        compact = re.sub(r"\s+", " ", str(value or "").strip())
        return compact.strip(" -,:;/")

    @classmethod
    def _tokenize(cls, value: str) -> List[str]:
        return [
            token
            for token in re.findall(r"[a-zA-Z0-9_+#/.-]+", cls._normalize_for_match(value))
            if len(token) >= 2
        ]

    @staticmethod
    def _dedupe_keep_order(values: Iterable[str], *, limit: int | None = None) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for value in values:
            item = re.sub(r"\s+", " ", str(value or "").strip())
            normalized = item.lower()
            if not item or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(item)
            if limit is not None and len(ordered) >= limit:
                break
        return ordered

    @classmethod
    def _phrase_expansions(cls, normalized_text: str) -> List[str]:
        expansions: List[str] = []
        phrase_items = sorted(
            cls._PHRASE_TRANSLATIONS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for phrase, aliases in phrase_items:
            if phrase in normalized_text:
                expansions.extend(aliases)
        for phrase, aliases in cls._ACTION_TRANSLATIONS.items():
            if phrase in normalized_text:
                expansions.extend(aliases)
        return cls._dedupe_keep_order(expansions)

    @classmethod
    def _looks_vietnamese(cls, sources: Sequence[str]) -> bool:
        haystack = " ".join(str(item or "") for item in sources)
        normalized = cls._normalize_for_match(haystack)
        return any(
            marker in normalized
            for marker in (
                " bai ",
                " hoc ",
                " vong lap ",
                " dieu kien ",
                " ham ",
                " lop ",
                " doi tuong ",
                " ngoai le ",
                " de quy ",
                " su dung ",
                " giai thich ",
                " ap dung ",
            )
        ) or bool(re.search(r"[à-ỹÀ-ỸđĐ]", haystack))

    @staticmethod
    def _json_payload(text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        candidate = raw[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _llm_cache_key(cls, sources: Sequence[str]) -> str:
        return " || ".join(cls._clean_phrase(source) for source in sources if cls._clean_phrase(source))

    @lru_cache(maxsize=256)
    def _rewrite_with_llm_cached(self, cache_key: str) -> Dict[str, Any]:
        if not self.client or not cache_key.strip():
            return {}
        if time.time() < self._llm_cooldown_until:
            return {}
        prompt = (
            "You are helping a learning retrieval system.\n"
            "Input may be a Vietnamese lesson description. Infer the learner intent and output English search terms.\n"
            "Return strict JSON only with this shape:\n"
            "{"
            "\"intent\":\"...\","
            "\"english_terms\":[\"...\"],"
            "\"concepts\":[\"...\"]"
            "}\n"
            "Rules:\n"
            "- Keep terms concise and retrieval-friendly.\n"
            "- Prioritize programming/computer science terminology.\n"
            "- Include synonyms when useful.\n"
            "- Do not include explanations outside JSON.\n"
            f"Lesson context:\n{cache_key}"
        )
        for attempt in range(1, self._LLM_MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=self._LLM_MODEL,
                    contents=prompt,
                    config={
                        "temperature": 0.2,
                        "max_output_tokens": 400,
                        "response_mime_type": "application/json",
                    },
                )
                payload = self._json_payload(getattr(response, "text", None) or "")
                if payload:
                    return payload
            except Exception as exc:  # pragma: no cover - optional dependency
                logger.warning(
                    "Lesson query rewrite failed on attempt %s/%s: %s",
                    attempt,
                    self._LLM_MAX_RETRIES,
                    exc,
                )
                cooldown = _lesson_query_quota_cooldown_seconds(exc)
                self._llm_cooldown_until = time.time() + max(
                    self._LLM_COOLDOWN_SECONDS,
                    cooldown or 0,
                )
                if cooldown is not None:
                    break
                time.sleep(min(attempt, 2))
        return {}

    def _rewrite_with_llm(self, sources: Sequence[str]) -> Dict[str, Any]:
        if not self._looks_vietnamese(sources):
            return {}
        return self._rewrite_with_llm_cached(self._llm_cache_key(sources))

    @classmethod
    def _english_domain_tokens(cls, sources: Sequence[str]) -> List[str]:
        tokens: List[str] = []
        for source in sources:
            for token in cls._tokenize(source):
                if token in cls._STOP_WORDS:
                    continue
                if token in cls._KEEP_TOKENS or re.fullmatch(r"[a-z][a-z0-9_+#/\-]{2,}", token):
                    tokens.append(token)
        return cls._dedupe_keep_order(tokens)

    def build_query_payload(
        self,
        *,
        title: str = "",
        summary: str = "",
        objectives: Sequence[str] | None = None,
        keywords: Sequence[str] | None = None,
        chapter_title: str = "",
        chapter_description: str = "",
        subject_title: str = "",
        subject_topic: str = "",
        goal: str = "",
        extra_terms: Sequence[str] | None = None,
    ) -> Dict[str, Any]:
        objectives = objectives or []
        keywords = keywords or []
        extra_terms = extra_terms or []
        sources = [
            title,
            summary,
            *[str(item) for item in objectives if item],
            *[str(item) for item in keywords if item],
            chapter_title,
            chapter_description,
            subject_title,
            subject_topic,
            goal,
            *[str(item) for item in extra_terms if item],
        ]
        cleaned_sources = [
            self._clean_phrase(source)
            for source in sources
            if self._clean_phrase(source)
        ]

        vietnamese_phrases: List[str] = []
        english_expansions: List[str] = []
        for source in cleaned_sources:
            vietnamese_phrases.append(source)
            english_expansions.extend(
                self._phrase_expansions(self._normalize_for_match(source))
            )

        english_terms = self._dedupe_keep_order(
            [*english_expansions, *self._english_domain_tokens(cleaned_sources)],
            limit=24,
        )
        ai_payload = self._rewrite_with_llm(cleaned_sources)
        ai_terms = self._dedupe_keep_order(
            [
                *[
                    str(item)
                    for item in ai_payload.get("english_terms", [])
                    if str(item).strip()
                ],
                *[
                    str(item)
                    for item in ai_payload.get("concepts", [])
                    if str(item).strip()
                ],
                str(ai_payload.get("intent") or ""),
            ],
            limit=12,
        )
        english_terms = self._dedupe_keep_order(
            [*ai_terms, *english_terms],
            limit=24,
        )
        vietnamese_terms = self._dedupe_keep_order(cleaned_sources, limit=16)
        bilingual_terms = self._dedupe_keep_order(
            [*english_terms, *vietnamese_terms],
            limit=28,
        )
        return {
            "intent": str(ai_payload.get("intent") or "").strip(),
            "english_terms": english_terms,
            "vietnamese_terms": vietnamese_terms,
            "bilingual_terms": bilingual_terms,
            "english_query": " ".join(english_terms).strip(),
            "bilingual_query": " ".join(bilingual_terms).strip(),
        }


lesson_semantic_query_service = LessonSemanticQueryService()
