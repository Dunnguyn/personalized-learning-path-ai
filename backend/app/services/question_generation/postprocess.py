"""Post-processing helpers for lesson question generation."""

from __future__ import annotations

import re
from typing import Type


def build_multiple_choice_prompt(
    *, lesson_title: str, category: str, focus_term: str
) -> str:
    del focus_term
    if category == "data_structure":
        return (
            f"Theo doan trich cua bai '{lesson_title}', "
            "cau truc du lieu nao duoc nhac den truc tiep?"
        )
    if category == "method":
        return (
            f"Theo doan trich cua bai '{lesson_title}', "
            "phuong thuc hoac ham nao xuat hien trong noi dung?"
        )
    if category == "data_type":
        return (
            f"Theo doan trich cua bai '{lesson_title}', "
            "kieu du lieu hoac khai niem nao duoc de cap?"
        )
    if category == "operator":
        return (
            f"Theo doan trich cua bai '{lesson_title}', "
            "toan tu hoac bieu thuc nao duoc nhac den?"
        )
    return (
        f"Theo doan trich cua bai '{lesson_title}', "
        "khai niem nao duoc nhac den truc tiep?"
    )


def build_short_answer_prompt(*, lesson_title: str, focus_term: str) -> str:
    if focus_term:
        return (
            f"Dựa trên đoạn trích của bài '{lesson_title}', hãy tóm tắt vai trò "
            f"hoặc ý nghĩa của '{focus_term}'."
        )
    return (
        f"Dựa trên đoạn trích của bài '{lesson_title}', "
        "hãy nêu ý chính của nội dung này."
    )


def summarize_excerpt(*, service_cls: Type[object], excerpt: str, focus_term: str) -> str:
    cleaned = re.sub(r"\s+", " ", excerpt or "").strip().strip('"')
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[\.\!\?])\s+", cleaned)
        if item.strip()
    ]
    if focus_term:
        for sentence in sentences:
            if focus_term in service_cls._normalize_text(sentence):
                snippet = sentence.split(",", 1)[0].strip()
                if len(snippet) < 24:
                    snippet = sentence[:140].strip()
                return snippet[:160].rstrip(" ,;:") + (
                    "..." if len(snippet) > 160 else ""
                )
    if sentences:
        sentence = sentences[0]
        snippet = sentence.split(",", 1)[0].strip()
        if len(snippet) < 24:
            snippet = sentence[:140].strip()
        return snippet[:160].rstrip(" ,;:") + (
            "..." if len(snippet) > 160 else ""
        )
    snippet = cleaned.split(",", 1)[0].strip()
    if len(snippet) < 24:
        snippet = cleaned[:140].strip()
    return snippet[:160].rstrip(" ,;:") + ("..." if len(snippet) > 160 else "")


def clean_true_false_statement(statement: str) -> str:
    text = re.sub(r"\s+", " ", str(statement or "")).strip().strip('"')
    text = text.replace("``", "").replace("''", "")
    text = text.replace("Ã¢", "")
    text = re.sub(r"\b([A-Za-z]{2,})\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\{[^\}]*\}", "", text)
    text = re.sub(r"\([^\)]*#.*?\)", "", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s*[:;]\s*$", "", text)
    return text.strip(" -")
