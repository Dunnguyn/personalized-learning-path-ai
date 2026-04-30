"""Learning-path concept graph helpers."""

from __future__ import annotations


def stable_concept_numeric_id(value: str, *, order: int) -> int:
    normalized = str(value or "").strip()
    if normalized.isdigit():
        return int(normalized)
    return 900000 + order
