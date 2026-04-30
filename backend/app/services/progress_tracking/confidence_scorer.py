import os
import re
import logging
import time
from typing import Optional

from backend.app.utils.gemini import get_gemini_client, get_gemini_client_manager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration
CONFIDENCE_MODEL = os.getenv("CONFIDENCE_MODEL", "models/gemini-2.5-flash")
DEFAULT_FALLBACK_SCORE = 0.5
MAX_QUESTION_LEN = 500
MAX_ANSWER_LEN = 2000
CONFIDENCE_QUOTA_COOLDOWN_SECONDS = int(
    os.getenv("CONFIDENCE_QUOTA_COOLDOWN_SECONDS", "120")
)
CONFIDENCE_COOLDOWN_UNTIL = 0.0

# Initialize client safely
client = None
try:
    client = get_gemini_client()
    if client is None:
        logger.warning("Gemini API key not set; confidence scoring will use fallback.")
except Exception as e:
    logger.exception("Failed to initialize Gemini client for confidence_scorer: %s", e)
    client = None


def _extract_text_from_response_object(response) -> Optional[str]:
    """
    Try common SDK response shapes to extract a primary text string.
    """
    if response is None:
        return None

    try:
        # direct text fields
        if hasattr(response, "text") and isinstance(response.text, str):
            return response.text
        if hasattr(response, "output_text") and isinstance(response.output_text, str):
            return response.output_text

        # response.output -> list -> content -> text
        out = getattr(response, "output", None) or (
            response.get("output") if isinstance(response, dict) else None
        )
        if out and isinstance(out, (list, tuple)) and len(out) > 0:
            first = out[0]
            content = getattr(first, "content", None) or (
                first.get("content") if isinstance(first, dict) else None
            )
            if content:
                if isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = getattr(piece, "text", None) or (
                        piece.get("text") if isinstance(piece, dict) else None
                    )
                    if isinstance(text, str):
                        return text
                elif isinstance(content, str):
                    return content

        # candidates pattern
        cand = getattr(response, "candidates", None) or (
            response.get("candidates") if isinstance(response, dict) else None
        )
        if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
            first = cand[0]
            content = (
                first.get("content")
                if isinstance(first, dict)
                else getattr(first, "content", None)
            )
            if isinstance(content, (list, tuple)) and len(content) > 0:
                piece = content[0]
                text = (
                    piece.get("text")
                    if isinstance(piece, dict)
                    else getattr(piece, "text", None)
                )
                if isinstance(text, str):
                    return text

        # choices/chat-like pattern
        choices = getattr(response, "choices", None) or (
            response.get("choices") if isinstance(response, dict) else None
        )
        if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
            first = choices[0]
            message = (
                first.get("message")
                if isinstance(first, dict)
                else getattr(first, "message", None)
            )
            if message:
                content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                if isinstance(content, str):
                    return content
                if isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    if isinstance(piece, str):
                        return piece
    except Exception as e:
        logger.debug("Error extracting text from response object: %s", e)

    return None


def _extract_number_from_text(text: str) -> Optional[float]:
    """
    Extract first numeric value between 0 and 1 from a text blob.
    Accept forms like "0.87", "0,87", "0.5", "1", "0"
    """
    if not text:
        return None

    # Normalize commas to dots
    cleaned = text.replace(",", ".")
    # Find floats or ints
    matches = re.findall(r"\b0(?:\.\d+)?\b|\b1(?:\.0+)?\b|\b0?\.\d+\b", cleaned)
    if not matches:
        # fallback: find any number-like token
        matches = re.findall(r"[-+]?\d*\.\d+|\d+", cleaned)
    for m in matches:
        try:
            val = float(m)
            if 0.0 <= val <= 1.0:
                return val
        except Exception:
            continue
    return None


def _parse_numeric_from_response(response) -> Optional[float]:
    """
    Try to extract a numeric score from the response object using multiple strategies.
    """
    # 1. Try direct extraction of text
    text = _extract_text_from_response_object(response)
    if text:
        num = _extract_number_from_text(text)
        if num is not None:
            return num

    # 2. If response is a dict-like with numeric fields, try common keys
    if isinstance(response, dict):
        for key in ("score", "value", "confidence", "result"):
            v = response.get(key)
            try:
                if isinstance(v, (int, float)):
                    val = float(v)
                    if 0.0 <= val <= 1.0:
                        return val
                if isinstance(v, str):
                    num = _extract_number_from_text(v)
                    if num is not None:
                        return num
            except Exception:
                continue

    # 3. Not found
    return None


def _confidence_quota_cooldown_seconds(error: Exception) -> Optional[int]:
    text = str(error)
    if "RESOURCE_EXHAUSTED" not in text and "Quota exceeded" not in text and "429" not in text:
        return None
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", text, re.IGNORECASE)
    if not match:
        match = re.search(r"retryDelay': '([0-9]+)s'", text)
    if match:
        return int(float(match.group(1)))
    return CONFIDENCE_QUOTA_COOLDOWN_SECONDS


def _confidence_scope_retry_after_seconds() -> float:
    status = get_gemini_client_manager().get_scope_status(
        scope=f"generate_content:{CONFIDENCE_MODEL}"
    )
    return max(0.0, float(status.get("retry_after_seconds", 0.0) or 0.0))


def score_confidence(
    question: str, answer: str, context: Optional[str] = None
) -> float:
    """
    Score the confidence of an answer in [0.0, 1.0].

    - Validates and truncates inputs.
    - Calls Gemini (if configured) trying multiple SDK call shapes.
    - Robustly extracts a numeric score from the response.
    - Returns a safe fallback (0.5) on any failure.
    """
    # Validate inputs
    if not question or not question.strip():
        logger.debug("Empty question provided to score_confidence; returning fallback.")
        return DEFAULT_FALLBACK_SCORE
    if not answer or not answer.strip():
        logger.debug("Empty answer provided to score_confidence; returning fallback.")
        return DEFAULT_FALLBACK_SCORE

    q = question.strip()[:MAX_QUESTION_LEN]
    a = answer.strip()[:MAX_ANSWER_LEN]
    ctx = (context.strip()[:4000]) if context else ""

    prompt = (
        "You are an AI tutor.\n\n"
        "Given the following question and an answer, return ONLY a single decimal number between 0.0 and 1.0\n"
        "that represents how correct and confident the answer is. No explanation, no extra text.\n\n"
        f"Question:\n{q}\n\n"
        f"Student Answer:\n{a}\n\n"
    )
    if ctx:
        prompt += f"Context (learning materials):\n{ctx}\n\n"

    prompt += "Return a single number between 0.0 and 1.0. Example: 0.87\n"

    # If client not initialized, return fallback
    if client is None:
        logger.debug(
            "Gemini client unavailable in score_confidence; returning fallback score."
        )
        return DEFAULT_FALLBACK_SCORE
    global CONFIDENCE_COOLDOWN_UNTIL
    if time.time() < CONFIDENCE_COOLDOWN_UNTIL:
        logger.debug("Confidence scorer cooldown active; returning fallback score.")
        return DEFAULT_FALLBACK_SCORE
    if _confidence_scope_retry_after_seconds() > 0:
        logger.debug(
            "Confidence scorer skipped because Gemini shared scope cooldown is active."
        )
        return DEFAULT_FALLBACK_SCORE

    try:
        responses_to_try = [
            client.models.generate_content(model=CONFIDENCE_MODEL, contents=prompt)
        ]

        # Try to parse numeric from attempted responses
        for resp in responses_to_try:
            num = _parse_numeric_from_response(resp)
            if num is not None:
                num = max(0.0, min(num, 1.0))
                logger.debug("Confidence score extracted: %s", num)
                return num

        # As a last resort, try parsing text from the latest response if any
        if responses_to_try:
            text = _extract_text_from_response_object(responses_to_try[-1])
            num = _extract_number_from_text(text or "")
            if num is not None:
                logger.debug(
                    "Confidence score extracted (fallback text parse): %s", num
                )
                return max(0.0, min(num, 1.0))

        logger.warning(
            "No numeric confidence extracted from Gemini responses; returning fallback."
        )
        return DEFAULT_FALLBACK_SCORE

    except Exception as e:
        cooldown = _confidence_quota_cooldown_seconds(e)
        if cooldown is not None:
            CONFIDENCE_COOLDOWN_UNTIL = time.time() + max(
                CONFIDENCE_QUOTA_COOLDOWN_SECONDS,
                cooldown,
            )
            logger.warning(
                "Confidence scorer quota exhausted; cooldown active for %ss",
                max(CONFIDENCE_QUOTA_COOLDOWN_SECONDS, cooldown),
            )
            return DEFAULT_FALLBACK_SCORE
        logger.exception("Exception while scoring confidence: %s", e)
        return DEFAULT_FALLBACK_SCORE
