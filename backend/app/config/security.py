"""Security-oriented configuration helpers."""

from __future__ import annotations

import os

INSECURE_SECRET_KEY_VALUES = {
    "",
    "change_this_secret_key",
    "your-secret-key-change-in-production",
    "your-super-secret-key-minimum-32-characters-long-change-in-production",
    "changeme",
    "secret",
    "development-secret",
}

TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag_enabled(name: str, default: bool = False) -> bool:
    """Return True when an environment flag is explicitly enabled."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in TRUE_VALUES


def is_secure_secret_key(value: str | None, minimum_length: int = 32) -> bool:
    """Validate that SECRET_KEY is not a short or placeholder value."""
    candidate = (value or "").strip()
    if len(candidate) < minimum_length:
        return False
    return candidate.lower() not in INSECURE_SECRET_KEY_VALUES
