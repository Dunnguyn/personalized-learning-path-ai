#!/usr/bin/env python3
"""
Check Gemini API key and model availability.

Usage:
  - Status check (no network): python check_gemini.py
  - Full test (makes a small API call): python check_gemini.py --test-generate
"""
import os
import argparse
import sys

DEFAULT_MODEL = "models/gemini-2.5-flash"

try:
    from backend.app.services.rag_pipeline import PRIMARY_MODEL as RAG_PRIMARY_MODEL
except Exception:
    RAG_PRIMARY_MODEL = DEFAULT_MODEL


def status():
    key = os.getenv("GEMINI_API_KEY")
    print("GEMINI_API_KEY:", "SET" if key else "NOT SET")
    try:
        import google.genai as genai_module  # type: ignore
        print("google.genai: installed")
    except Exception as e:
        print("google.genai: NOT installed -", e)
        return False, None

    if not key:
        return False, None

    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=key)
        print("Client: created")
        return True, client
    except Exception as e:
        print("Client: creation failed -", e)
        return False, None


def test_generate(client, model, prompt="Hello"):
    try:
        print(f"Testing model: {model} (prompt: {prompt!r})")
        resp = client.models.generate_content(model=model, contents=prompt)
        # response shape may vary; try .text then fallback to repr
        text = getattr(resp, "text", None)
        if text is None:
            print("Response:", repr(resp))
        else:
            print("Response text:", text.strip())
        return True
    except Exception as e:
        print("API call failed -", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Check Gemini API key and model")
    parser.add_argument("--test-generate", action="store_true", help="Make a small API call to validate key & model")
    parser.add_argument("--model", type=str, default=RAG_PRIMARY_MODEL, help="Model name to test")
    parser.add_argument("--prompt", type=str, default="Hello from key test", help="Prompt for test generate")
    args = parser.parse_args()

    ok, client = status()
    if not ok and not args.test_generate:
        sys.exit(1)

    if args.test_generate:
        if client is None:
            print("Cannot perform generate: client not available.")
            sys.exit(1)
        success = test_generate(client, args.model, prompt=args.prompt)
        sys.exit(0 if success else 2)


if __name__ == "__main__":
    main()