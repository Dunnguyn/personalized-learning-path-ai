from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(REPO_ROOT / ".env", override=True)

from backend.app.utils.gemini import (  # noqa: E402
    configured_gemini_api_key_count,
    get_gemini_client,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simple Gemini smoke test using the project's rotating API-key client."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Xin chao Gemini",
        help="Prompt sent to Gemini.",
    )
    parser.add_argument(
        "--model",
        default="models/gemini-2.5-flash",
        help="Gemini model name.",
    )
    args = parser.parse_args()

    key_count = configured_gemini_api_key_count()
    print(f"Configured Gemini API keys: {key_count}")

    client = get_gemini_client()
    if client is None:
        print(
            "No Gemini API key configured. Set GEMINI_API_KEY, GEMINI_API_KEYS, "
            "or GEMINI_API_KEY_1..N."
        )
        return 1

    try:
        response = client.models.generate_content(
            model=args.model,
            contents=args.prompt,
        )
    except Exception as exc:
        print(f"Gemini request failed after trying available keys: {exc}")
        return 2

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        print("Gemini returned an empty response.")
        return 3

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
