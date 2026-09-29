"""Small helpers for request-scoped performance timing."""

from __future__ import annotations

from typing import MutableMapping


def add_timing(
    timings: MutableMapping[str, float] | None,
    key: str,
    elapsed_seconds: float,
) -> None:
    """Accumulate elapsed time in milliseconds for a timing bucket."""
    if timings is None:
        return
    timings[key] = round(float(timings.get(key, 0.0)) + elapsed_seconds * 1000.0, 3)
