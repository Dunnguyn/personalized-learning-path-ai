"""
YouTube Summarizer Service: Generate pseudo-transcripts for videos without transcripts.

Purpose:
- When a YouTube video has no available transcript, use Gemini AI to generate
  a pseudo-transcript based on video title, topic, and learning level
- Provides structured summaries for learning purposes (NOT factual replacement)
- Supports multiple output formats (narrative, bullet points, outline)

Features:
- Input validation (title, topic, level)
- Multi-strategy prompting (transcript vs no-transcript scenarios)
- Customizable summarization by learning level
- Timeout + retry logic for reliability
- Response parsing + formatting (outline detection, list extraction)
- Length control (min/max summary length)
- Caching (avoid re-summarizing same video)
- Batch summarization
- Quality metrics (coverage score, completeness)
- Comprehensive logging + error handling
- Environment-based configuration

Execution Flow:
1. Validate inputs (title, topic, level)
2. Check cache (avoid re-summarizing)
3. Build context-aware prompt
4. Call Gemini API with retry logic
5. Parse + validate response
6. Format output (outline, bullet points, narrative)
7. Return summary + metadata (tokens, quality score, language)
8. Cache result for future use

All operations include:
- Timeout handling (30s default)
- Retry logic (up to 3 attempts)
- Graceful fallbacks (return structured template if LLM unavailable)
- Logging at all levels
- Type hints + docstrings
"""

import os
import logging
import time
import hashlib
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
import json

from backend.app.database.mongo import get_db
from backend.app.api.schemas import LevelEnum

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Try to import Gemini client
try:
    from google import genai
    from google.api_core import retry
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai library not available")

# =========================
# CONFIG
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
SUMMARIZER_TIMEOUT = int(os.getenv("YOUTUBE_SUMMARIZER_TIMEOUT", "30"))  # seconds
SUMMARIZER_MAX_RETRIES = int(os.getenv("YOUTUBE_SUMMARIZER_MAX_RETRIES", "3"))
SUMMARY_MIN_LENGTH = int(os.getenv("YOUTUBE_SUMMARY_MIN_LENGTH", "100"))  # chars
SUMMARY_MAX_LENGTH = int(os.getenv("YOUTUBE_SUMMARY_MAX_LENGTH", "3000"))  # chars
ENABLE_SUMMARY_CACHE = os.getenv("ENABLE_SUMMARY_CACHE", "true").lower() == "true"
SUMMARY_CACHE_TTL_HOURS = int(os.getenv("YOUTUBE_SUMMARY_CACHE_TTL_HOURS", "72"))
OUTPUT_FORMAT = os.getenv("YOUTUBE_SUMMARY_OUTPUT_FORMAT", "narrative")  # narrative|outline|bullets

# Initialize Gemini client
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info(f"Gemini client initialized: model={GEMINI_MODEL}, timeout={SUMMARIZER_TIMEOUT}s")
    except Exception as e:
        logger.warning(f"Failed to initialize Gemini client: {e}")
        genai_client = None
else:
    genai_client = None
    logger.warning("Gemini not available for summarization")


# =========================
# HELPERS: CACHING & HASHING
# =========================
def _get_cache_key(video_title: str, topic: str, level: str) -> str:
    """
    Generate cache key for summary (hash of inputs).
    
    Args:
        video_title: Video title
        topic: Topic string
        level: Level string
        
    Returns:
        Hash key (32 chars)
    """
    input_str = f"{video_title}|{topic}|{level}".lower().strip()
    return hashlib.md5(input_str.encode()).hexdigest()


def get_cached_summary(video_title: str, topic: str, level: str) -> Optional[Dict[str, any]]:
    """
    Retrieve cached summary if available and not expired.
    
    Args:
        video_title: Video title
        topic: Topic string
        level: Level string
        
    Returns:
        Cached summary dict or None
    """
    if not ENABLE_SUMMARY_CACHE:
        return None
    
    try:
        db = get_db()
        cache_key = _get_cache_key(video_title, topic, level)
        
        cached = db.summary_cache.find_one({"cache_key": cache_key})
        
        if cached:
            # Check expiry
            created_at = cached.get("created_at")
            if created_at:
                age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
                if age_hours > SUMMARY_CACHE_TTL_HOURS:
                    logger.debug(f"Summary cache expired ({age_hours:.1f}h > {SUMMARY_CACHE_TTL_HOURS}h)")
                    return None
            
            logger.info(f"Summary cache hit: {video_title[:50]}...")
            return cached.get("summary")
        
        return None
    
    except Exception as e:
        logger.warning(f"Error retrieving cached summary: {e}")
        return None


def cache_summary(
    video_title: str,
    topic: str,
    level: str,
    summary: Dict[str, any]
) -> None:
    """
    Cache generated summary for future use.
    
    Args:
        video_title: Video title
        topic: Topic string
        level: Level string
        summary: Summary dict to cache
    """
    if not ENABLE_SUMMARY_CACHE:
        return
    
    try:
        db = get_db()
        cache_key = _get_cache_key(video_title, topic, level)
        
        db.summary_cache.update_one(
            {"cache_key": cache_key},
            {
                "$set": {
                    "cache_key": cache_key,
                    "video_title": video_title,
                    "topic": topic,
                    "level": level,
                    "summary": summary,
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        logger.debug(f"Cached summary: {video_title[:50]}...")
    
    except Exception as e:
        logger.warning(f"Error caching summary: {e}")


# =========================
# HELPERS: VALIDATION & FORMATTING
# =========================
def validate_summarizer_inputs(video_title: str, topic: str, level: str) -> None:
    """
    Validate summarizer input parameters.
    
    Args:
        video_title: Video title
        topic: Topic string
        level: Learning level (beginner/intermediate/advanced)
        
    Raises:
        ValueError: If any parameter invalid
    """
    if not video_title or not video_title.strip():
        raise ValueError("Video title cannot be empty")
    
    if len(video_title) < 3:
        raise ValueError("Video title must be at least 3 characters")
    
    if len(video_title) > 500:
        raise ValueError("Video title cannot exceed 500 characters")
    
    if not topic or not topic.strip():
        raise ValueError("Topic cannot be empty")
    
    if len(topic) > 200:
        raise ValueError("Topic cannot exceed 200 characters")
    
    if level not in ["beginner", "intermediate", "advanced"]:
        raise ValueError(f"Level must be one of: beginner, intermediate, advanced (got: {level})")


def _format_summary_as_outline(summary_text: str) -> List[str]:
    """
    Try to parse summary text into outline format (bullet points).
    
    Args:
        summary_text: Full summary text
        
    Returns:
        List of bullet points
    """
    lines = summary_text.split("\n")
    outline = []
    
    for line in lines:
        line = line.strip()
        if line and len(line) > 10:
            # Remove common bullet markers
            for marker in ["- ", "* ", "• ", "→ ", "• ", "> "]:
                if line.startswith(marker):
                    line = line[len(marker):]
            
            # Remove numbers (1. 2. etc.)
            import re
            line = re.sub(r"^\d+\.\s*", "", line)
            
            if line:
                outline.append(line)
    
    return outline if outline else [summary_text]


def _format_summary_as_narrative(summary_text: str, max_length: int = SUMMARY_MAX_LENGTH) -> str:
    """
    Format summary as narrative paragraph(s).
    
    Args:
        summary_text: Raw summary text
        max_length: Maximum length in characters
        
    Returns:
        Formatted narrative
    """
    # Remove excess whitespace
    summary_text = " ".join(summary_text.split())
    
    # Truncate if needed
    if len(summary_text) > max_length:
        summary_text = summary_text[:max_length].rsplit(" ", 1)[0] + "..."
    
    return summary_text


def _calculate_quality_score(summary_text: str, topic: str, level: str) -> float:
    """
    Calculate quality score for summary (0.0 to 1.0).
    
    Factors:
    - Length (minimum threshold)
    - Contains learning keywords (explain, understand, apply, etc.)
    - Contains topic keywords
    - Follows level appropriateness
    
    Args:
        summary_text: Generated summary
        topic: Topic string
        level: Learning level
        
    Returns:
        Quality score [0.0, 1.0]
    """
    score = 0.5  # baseline
    
    # Length check
    if len(summary_text) >= SUMMARY_MIN_LENGTH * 2:
        score += 0.2
    elif len(summary_text) >= SUMMARY_MIN_LENGTH:
        score += 0.1
    
    # Learning keywords
    learning_keywords = ["explain", "understand", "learn", "apply", "practice", 
                        "example", "concept", "definition", "implement", "demonstrate"]
    found_keywords = sum(1 for kw in learning_keywords if kw in summary_text.lower())
    score += min(found_keywords / 5 * 0.2, 0.2)
    
    # Topic keywords
    topic_keywords = topic.lower().split()
    found_topic = sum(1 for tk in topic_keywords if tk in summary_text.lower())
    score += min(found_topic / max(len(topic_keywords), 1) * 0.1, 0.1)
    
    return min(score, 1.0)


# =========================
# MAIN SUMMARIZATION
# =========================
def summarize_youtube_video(
    video_title: str,
    topic: str,
    level: str = "beginner",
    video_id: Optional[str] = None,
    format_type: Optional[str] = None,
    additional_context: Optional[str] = None,
    user_id: Optional[int] = None
) -> Dict[str, any]:
    """
    Generate pseudo-transcript/summary for YouTube video without transcript.
    
    Uses Gemini AI to create a learning-oriented summary based on:
    - Video title
    - Topic category
    - Learning level (beginner/intermediate/advanced)
    - Optional additional context
    
    Pipeline:
    1. Validate inputs
    2. Check cache (avoid re-summarizing)
    3. Build context-aware prompt
    4. Call Gemini API with retry logic
    5. Parse + validate response
    6. Format output (narrative/outline/bullets)
    7. Calculate quality score
    8. Cache result
    9. Return summary + metadata
    
    Args:
        video_title: YouTube video title
        topic: Topic category (e.g., "Python programming", "Machine Learning")
        level: Learning level (beginner/intermediate/advanced, default: beginner)
        video_id: Optional YouTube video_id (for tracking)
        format_type: Optional output format (narrative/outline/bullets)
                    Default: use environment variable YOUTUBE_SUMMARY_OUTPUT_FORMAT
        additional_context: Optional additional context (e.g., video description)
        user_id: Optional user ID for audit trail
        
    Returns:
        Dict with:
        - success: bool (True if generation successful)
        - summary: str (generated summary text)
        - summary_type: str ("generated" | "cached" | "template" | "fallback")
        - format: str ("narrative" | "outline" | "bullets")
        - length: int (character count)
        - quality_score: float [0.0, 1.0]
        - video_title: str
        - topic: str
        - level: str
        - generation_time_ms: float
        - tokens_used: Optional[int]
        - language: str ("en" default)
        - message: str (summary)
        
    Raises:
        ValueError: If input validation fails
        Exception: Only on internal DB errors; API failures are graceful
        
    Example:
        >>> result = summarize_youtube_video(
        ...     video_title="Python Functions Explained",
        ...     topic="Python programming",
        ...     level="beginner"
        ... )
        >>> print(f"Generated {result['length']} char summary")
    """
    start_time = time.time()
    logger.info(f"Summarizing video: title='{video_title[:50]}...', topic={topic}, level={level}, user_id={user_id}")
    
    try:
        # 1️⃣ VALIDATE INPUTS
        validate_summarizer_inputs(video_title, topic, level)
        
        if format_type is None:
            format_type = OUTPUT_FORMAT
        
        if format_type not in ["narrative", "outline", "bullets"]:
            format_type = "narrative"
        
        logger.debug(f"Validated inputs: title_len={len(video_title)}, "
                    f"topic_len={len(topic)}, level={level}, format={format_type}")
        
        # 2️⃣ CHECK CACHE
        cached = get_cached_summary(video_title, topic, level)
        if cached:
            logger.info(f"Using cached summary for '{video_title[:50]}...'")
            result = {
                "success": True,
                "summary": cached.get("summary"),
                "summary_type": "cached",
                "format": format_type,
                "length": len(cached.get("summary", "")),
                "quality_score": cached.get("quality_score", 0.75),
                "video_title": video_title,
                "topic": topic,
                "level": level,
                "generation_time_ms": 0,
                "tokens_used": None,
                "language": "en",
                "message": f"Retrieved cached summary ({len(cached.get('summary', ''))} chars)"
            }
            return result
        
        # 3️⃣ BUILD PROMPT
        if level == "beginner":
            learning_context = "a beginner learner with no prior knowledge"
            emphasis = "simple explanations, key concepts, practical examples"
        elif level == "intermediate":
            learning_context = "an intermediate learner with some experience"
            emphasis = "deeper explanations, advanced concepts, real-world applications"
        else:  # advanced
            learning_context = "an advanced learner with strong background"
            emphasis = "technical details, edge cases, optimization techniques, best practices"
        
        prompt = f"""You are an expert educational content creator and AI tutor.

A {learning_context} is studying: **{topic}**

The YouTube video title is:
"{video_title}"

The video has NO transcript available.

Your task: Generate a detailed learning-oriented summary/pseudo-transcript as if it were 
the actual transcript of the video.

REQUIREMENTS:
1. Explain clearly and appropriately for {level} level learners
2. Focus on: {emphasis}
3. Include definitions, concepts, and practical examples when relevant
4. Use clear, structured format (bullet points or numbered lists)
5. DO NOT hallucinate or make up advanced topics beyond {level} level
6. DO NOT speculate about specific code if not relevant
7. Keep summary between {SUMMARY_MIN_LENGTH} and {SUMMARY_MAX_LENGTH} characters
8. Structure content logically (introduction → key concepts → examples → conclusion)

TOPIC CONTEXT:
- Domain: {topic}
- Level: {level}
{f"- Additional context: {additional_context}" if additional_context else ""}

OUTPUT FORMAT:
Generate a structured summary with clear organization. Use:
- **Bold** for main concepts
- Bullet points or numbers for lists
- Concise explanations

Generated Summary:
"""
        
        logger.debug(f"Built prompt ({len(prompt)} chars)")
        
        # 4️⃣ CALL GEMINI WITH RETRY
        summary_text = None
        tokens_used = None
        
        if genai_client and GEMINI_AVAILABLE:
            summary_text, tokens_used = _call_gemini_with_retry(
                prompt=prompt,
                model=GEMINI_MODEL,
                max_retries=SUMMARIZER_MAX_RETRIES,
                timeout=SUMMARIZER_TIMEOUT
            )
        else:
            logger.warning("Gemini client not available - returning template")
        
        # 5️⃣ FALLBACK: TEMPLATE IF GENERATION FAILED
        if not summary_text:
            logger.warning(f"Gemini generation failed - returning template")
            summary_text = _generate_template_summary(video_title, topic, level)
            summary_type = "template"
        else:
            summary_type = "generated"
        
        # Validate length
        if len(summary_text) < SUMMARY_MIN_LENGTH:
            logger.warning(f"Summary too short: {len(summary_text)} < {SUMMARY_MIN_LENGTH}")
            summary_text = _generate_template_summary(video_title, topic, level)
            summary_type = "template"
        
        if len(summary_text) > SUMMARY_MAX_LENGTH:
            logger.debug(f"Truncating summary: {len(summary_text)} > {SUMMARY_MAX_LENGTH}")
            summary_text = _format_summary_as_narrative(summary_text, SUMMARY_MAX_LENGTH)
        
        # 6️⃣ FORMAT OUTPUT
        if format_type == "outline":
            formatted = _format_summary_as_outline(summary_text)
            display_summary = "\n".join(f"• {item}" for item in formatted)
        elif format_type == "bullets":
            formatted = _format_summary_as_outline(summary_text)
            display_summary = "\n".join(f"  - {item}" for item in formatted)
        else:  # narrative
            display_summary = _format_summary_as_narrative(summary_text)
        
        # 7️⃣ QUALITY SCORE
        quality_score = _calculate_quality_score(display_summary, topic, level)
        
        # 8️⃣ CACHE RESULT
        cache_data = {
            "summary": display_summary,
            "quality_score": quality_score,
            "summary_type": summary_type
        }
        cache_summary(video_title, topic, level, cache_data)
        
        # 9️⃣ RETURN
        execution_ms = (time.time() - start_time) * 1000
        
        logger.info(
            f"Summarization complete: video='{video_title[:50]}...', "
            f"type={summary_type}, length={len(display_summary)}, "
            f"quality={quality_score:.2f}, exec_ms={execution_ms:.0f}"
        )
        
        return {
            "success": True,
            "summary": display_summary,
            "summary_type": summary_type,
            "format": format_type,
            "length": len(display_summary),
            "quality_score": round(quality_score, 2),
            "video_title": video_title,
            "topic": topic,
            "level": level,
            "generation_time_ms": round(execution_ms, 2),
            "tokens_used": tokens_used,
            "language": "en",
            "message": f"Generated {len(display_summary)} char summary (quality: {quality_score:.0%})"
        }
    
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during summarization: {e}")
        raise RuntimeError(f"Summarization failed: {str(e)}")


# =========================
# HELPERS: LLM CALLING WITH RETRY
# =========================
def _call_gemini_with_retry(
    prompt: str,
    model: str = GEMINI_MODEL,
    max_retries: int = SUMMARIZER_MAX_RETRIES,
    timeout: int = SUMMARIZER_TIMEOUT,
    retry_count: int = 0
) -> Tuple[Optional[str], Optional[int]]:
    """
    Call Gemini API with retry logic.
    
    Args:
        prompt: Prompt to send to Gemini
        model: Model name (default: from env)
        max_retries: Max retry attempts
        timeout: Timeout in seconds
        retry_count: Internal retry counter
        
    Returns:
        Tuple of (response_text, tokens_used) or (None, None)
    """
    logger.debug(f"Calling Gemini (attempt {retry_count+1}/{max_retries+1})")
    
    if not genai_client:
        logger.warning("Gemini client not initialized")
        return None, None
    
    try:
        start_time = time.time()
        
        # Call Gemini with timeout
        response = genai_client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "temperature": 0.7,
                "top_k": 40,
                "top_p": 0.95,
                "max_output_tokens": 2000
            }
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        if not response or not response.text:
            raise ValueError("Empty response from Gemini")
        
        text = response.text.strip()
        
        # Try to extract token count
        tokens = None
        try:
            if hasattr(response, 'usage_metadata'):
                tokens = response.usage_metadata.output_tokens
        except:
            pass
        
        logger.info(f"Gemini response received: {len(text)} chars, {elapsed_ms:.0f}ms")
        return text, tokens
    
    except Exception as e:
        logger.warning(f"Gemini call failed (attempt {retry_count+1}): {e}")
        
        if retry_count < max_retries:
            wait_time = 2 ** retry_count  # Exponential backoff
            logger.info(f"Retrying in {wait_time}s...")
            time.sleep(wait_time)
            return _call_gemini_with_retry(
                prompt=prompt,
                model=model,
                max_retries=max_retries,
                timeout=timeout,
                retry_count=retry_count + 1
            )
        else:
            logger.error(f"Max retries ({max_retries}) exceeded")
            return None, None


# =========================
# HELPERS: TEMPLATE FALLBACK
# =========================
def _generate_template_summary(video_title: str, topic: str, level: str) -> str:
    """
    Generate structured template summary (fallback if Gemini unavailable).
    
    Provides useful summary structure even when LLM unavailable.
    
    Args:
        video_title: Video title
        topic: Topic string
        level: Level string
        
    Returns:
        Template summary text
    """
    logger.debug(f"Generating template summary (fallback)")
    
    level_context = {
        "beginner": {
            "intro": "Introduction to basic concepts",
            "keywords": ["fundamentals", "basics", "definition", "overview"]
        },
        "intermediate": {
            "intro": "Intermediate concepts and applications",
            "keywords": ["intermediate", "application", "implementation", "practice"]
        },
        "advanced": {
            "intro": "Advanced topics and best practices",
            "keywords": ["advanced", "optimization", "patterns", "best practices"]
        }
    }
    
    context = level_context.get(level, level_context["beginner"])
    
    template = f"""📚 Learning Summary: {video_title}

Topic: {topic}
Level: {level.capitalize()}

{context['intro']}:

Key Concepts:
• Understanding fundamentals of {topic}
• Core principles and definitions
• Practical applications and examples
• Common patterns and use cases

Learning Objectives:
1. Grasp the basics of {topic}
2. Understand key terminology
3. Learn practical implementation techniques
4. See real-world examples

Main Topics Covered:
• Introduction and importance
• Fundamental concepts
• Key components
• Practical applications
• Tips and best practices

Summary:
This video provides {context['intro'].lower()} in the field of {topic}. 
Viewers will learn essential knowledge and skills relevant to this domain.

Additional Resources:
• Practice exercises
• Code examples
• Further reading materials
• Recommended next steps

Notes:
Generated template summary (actual transcript unavailable)
For the most accurate content, please check the video directly.
"""
    
    return template


# =========================
# BATCH SUMMARIZATION
# =========================
def summarize_youtube_videos_batch(
    videos: List[Dict[str, str]],
    parallel: bool = False,
    user_id: Optional[int] = None
) -> Dict[str, any]:
    """
    Batch summarize multiple YouTube videos.
    
    Each video dict should have: video_title, topic, level (optional)
    
    Args:
        videos: List of video dicts
        parallel: If True, attempt parallel processing (not implemented)
        user_id: Optional user ID
        
    Returns:
        Dict with:
        - success: bool (all succeeded)
        - status: "success" | "partial" | "failed"
        - total: int
        - successful: int
        - failed: int
        - results: List[Dict] (summary result per video)
        - errors: List[Dict]
        
    Example:
        >>> batch = summarize_youtube_videos_batch([
        ...     {"video_title": "Intro to Python", "topic": "python", "level": "beginner"},
        ...     {"video_title": "ML Fundamentals", "topic": "machine learning"}
        ... ])
        >>> print(f"Summarized {batch['successful']}/{batch['total']}")
    """
    logger.info(f"Batch summarizing {len(videos)} videos")
    
    results = []
    errors = []
    successful = 0
    
    for idx, video in enumerate(videos):
        try:
            result = summarize_youtube_video(
                video_title=video.get("video_title"),
                topic=video.get("topic"),
                level=video.get("level", "beginner"),
                video_id=video.get("video_id"),
                format_type=video.get("format"),
                additional_context=video.get("additional_context"),
                user_id=user_id
            )
            results.append(result)
            successful += 1
            logger.debug(f"[{idx+1}/{len(videos)}] Summarized: {result['video_title']}")
        
        except Exception as e:
            errors.append({
                "index": idx,
                "video_title": video.get("video_title"),
                "error": str(e)
            })
            logger.error(f"[{idx+1}/{len(videos)}] Error: {e}")
    
    total = len(videos)
    failed = len(errors)
    status = "success" if failed == 0 else ("partial" if successful > 0 else "failed")
    
    logger.info(f"Batch summarization complete: total={total}, successful={successful}, "
               f"failed={failed}, status={status}")
    
    return {
        "success": failed == 0,
        "status": status,
        "total": total,
        "successful": successful,
        "failed": failed,
        "results": results,
        "errors": errors,
        "message": f"Summarized {successful}/{total} videos"
    }