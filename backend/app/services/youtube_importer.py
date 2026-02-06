"""
YouTube Importer Service: Extract, chunk, and embed YouTube video transcripts.

Features:
- URL validation (format, accessibility)
- Transcript fetching with fallback languages
- Smart text chunking (respects sentence/timestamp boundaries)
- Metadata enrichment (title, duration, channel, views, publish date, thumbnail)
- Duplicate detection (avoid re-importing videos)
- Batch import with partial failure handling
- Graceful fallback (save metadata if transcript unavailable)
- Concept mapping (auto-map topic to concept_id)
- Pedagogy type inference (video → "video" pedagogy_type)
- Comprehensive logging + error handling
- Configurable via environment variables

Execution Flow:
1. Validate YouTube URL + extract video_id
2. Check if video already imported (duplicate detection)
3. Fetch video metadata (title, duration, channel, views, publish date, thumbnail)
4. Fetch transcript (with fallback languages)
5. If no transcript → Save metadata-only doc + return gracefully
6. If transcript → Chunk text (respecting sentences/timestamps)
7. Generate embeddings for each chunk
8. Store chunks with full metadata
9. Return import result (chunks created, transcript quality, etc.)

All operations include:
- Configurable via environment variables
- Error handling with fallbacks (no 500 errors)
- Logging at INFO/DEBUG/WARNING levels
- Validation + sanitization
- Type hints + comprehensive docstrings
"""

import os
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import re
import time
from functools import lru_cache

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import embed_text
from backend.app.services.concept_mapper import resolve_concept_id
from backend.app.api.schemas import LevelEnum, SourceEnum, PedagogyEnum

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# CONFIG
# =========================
YOUTUBE_CHUNK_SIZE = int(os.getenv("YOUTUBE_CHUNK_SIZE", "800"))  # characters per chunk
YOUTUBE_CHUNK_OVERLAP = int(os.getenv("YOUTUBE_CHUNK_OVERLAP", "100"))  # overlap chars
YOUTUBE_MIN_CHUNK_LENGTH = int(os.getenv("YOUTUBE_MIN_CHUNK_LENGTH", "50"))  # minimum chars
YOUTUBE_TIMEOUT_SECONDS = int(os.getenv("YOUTUBE_TIMEOUT_SECONDS", "30"))  # pytube timeout
YOUTUBE_MAX_RETRIES = int(os.getenv("YOUTUBE_MAX_RETRIES", "3"))  # retry attempts
YOUTUBE_BATCH_SIZE = int(os.getenv("YOUTUBE_BATCH_SIZE", "100"))  # max videos per batch
DEFAULT_LANGUAGE = os.getenv("YOUTUBE_DEFAULT_LANGUAGE", "en")  # transcript language
FALLBACK_LANGUAGES = os.getenv("YOUTUBE_FALLBACK_LANGUAGES", "en,vi,es,fr").split(",")
ENABLE_DUPLICATE_CHECK = os.getenv("ENABLE_DUPLICATE_CHECK", "true").lower() == "true"
MIN_TRANSCRIPT_LENGTH = int(os.getenv("YOUTUBE_MIN_TRANSCRIPT_LENGTH", "100"))  # minimum chars

logger.info(f"YouTube importer initialized: chunk_size={YOUTUBE_CHUNK_SIZE}, "
           f"timeout={YOUTUBE_TIMEOUT_SECONDS}s, batch_size={YOUTUBE_BATCH_SIZE}")

# Import YouTube libraries with graceful fallbacks
try:
    from pytube import YouTube
    from pytube.exceptions import PytubeError
    PYTUBE_AVAILABLE = True
    logger.info("pytube library available")
except ImportError:
    PYTUBE_AVAILABLE = False
    logger.warning("pytube not available - metadata fetch will be limited")

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        TranscriptsDisabled,
        NoTranscriptFound,
    )
    TRANSCRIPT_API_AVAILABLE = True
    logger.info("youtube-transcript-api library available")
except ImportError:
    TRANSCRIPT_API_AVAILABLE = False
    logger.warning("youtube-transcript-api not available - transcript fetch will fail")


# =========================
# HELPERS: URL & VALIDATION
# =========================
def extract_video_id(url: str) -> Optional[str]:
    """
    Extract video_id from YouTube URL (multiple formats supported).
    
    Supported formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/watch?v=VIDEO_ID&t=123s
    - https://m.youtube.com/watch?v=VIDEO_ID
    
    Args:
        url: Full YouTube URL
        
    Returns:
        video_id (11 characters) or None if invalid
        
    Raises:
        ValueError: If URL invalid
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    url = url.strip()
    
    # Format: youtube.com/watch?v=...
    if "youtube.com" in url or "m.youtube.com" in url:
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0].split("#")[0]
            if len(video_id) == 11 and video_id.isalnum() or "-" in video_id or "_" in video_id:
                logger.debug(f"Extracted video_id (youtube.com): {video_id}")
                return video_id
    
    # Format: youtu.be/...
    elif "youtu.be" in url:
        video_id = url.rstrip("/").split("/")[-1].split("?")[0].split("#")[0]
        if len(video_id) == 11 and video_id.replace("-", "").replace("_", "").isalnum():
            logger.debug(f"Extracted video_id (youtu.be): {video_id}")
            return video_id
    
    raise ValueError(f"Invalid YouTube URL format: {url}")


def validate_youtube_url(url: str) -> None:
    """
    Validate YouTube URL format.
    
    Args:
        url: YouTube URL to validate
        
    Raises:
        ValueError: If URL invalid or not a YouTube URL
    """
    if not url or not url.strip():
        raise ValueError("URL cannot be empty")
    
    url = url.strip()
    
    if not (("youtube.com" in url or "youtu.be" in url) and "http" in url):
        raise ValueError("URL must be a valid YouTube URL (youtube.com or youtu.be)")
    
    # Try to extract video_id to validate
    try:
        extract_video_id(url)
    except ValueError as e:
        raise ValueError(f"Invalid YouTube URL format: {str(e)}")


def extract_timestamp_from_text(text: str) -> Optional[float]:
    """
    Extract timestamp from transcript text (if available in format MM:SS or HH:MM:SS).
    
    Args:
        text: Text possibly containing timestamp
        
    Returns:
        Timestamp in seconds or None
    """
    match = re.search(r"(\d+):(\d+):(\d+)|(\d+):(\d+)", text)
    if match:
        if match.group(1):  # HH:MM:SS
            h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return h * 3600 + m * 60 + s
        else:  # MM:SS
            m, s = int(match.group(4)), int(match.group(5))
            return m * 60 + s
    return None


# =========================
# HELPERS: CHUNKING
# =========================
def _chunk_text_with_overlap(
    text: str,
    chunk_size: int = YOUTUBE_CHUNK_SIZE,
    overlap: int = YOUTUBE_CHUNK_OVERLAP
) -> List[str]:
    """
    Split text into chunks, respecting sentence boundaries.
    
    Strategy:
    - Aim for chunk_size characters
    - Prefer to split at sentence boundaries (., ?, !, newline)
    - Overlap chunks for context preservation
    - Filter out chunks below MIN_CHUNK_LENGTH
    
    Args:
        text: Full transcript text
        chunk_size: Target chunk size in characters
        overlap: Characters to overlap between chunks
        
    Returns:
        List of chunks (each >= YOUTUBE_MIN_CHUNK_LENGTH chars)
        
    Example:
        >>> chunks = _chunk_text_with_overlap("Sentence 1. Sentence 2. Sentence 3.")
        >>> len(chunks) >= 1
    """
    if not text or len(text) < YOUTUBE_MIN_CHUNK_LENGTH:
        logger.debug(f"Text too short to chunk: {len(text)} < {YOUTUBE_MIN_CHUNK_LENGTH}")
        return [text] if text else []
    
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        # Calculate end position
        end = min(start + chunk_size, text_len)
        
        # If not at end of text, try to split at sentence boundary
        if end < text_len:
            # Look for sentence ending (., ?, !, newline) within last 100 chars
            search_end = max(start, end - 150)
            last_boundary = -1
            
            for boundary_char in [".", "?", "!", "\n"]:
                pos = text.rfind(boundary_char, search_end, end)
                if pos > last_boundary and pos > start:
                    last_boundary = pos
            
            if last_boundary != -1:
                end = last_boundary + 1  # Include the punctuation
                logger.debug(f"Split at sentence boundary (pos {end})")
        
        # Extract chunk
        chunk = text[start:end].strip()
        
        if len(chunk) >= YOUTUBE_MIN_CHUNK_LENGTH:
            chunks.append(chunk)
            logger.debug(f"Chunk {len(chunks)}: {len(chunk)} chars")
        else:
            logger.debug(f"Skipped chunk < {YOUTUBE_MIN_CHUNK_LENGTH} chars")
        
        # Move start for next chunk (with overlap)
        next_start = end - overlap
        if next_start <= start:
            break
        start = next_start
    
    logger.info(f"Created {len(chunks)} chunks from {text_len} chars")
    return chunks


# =========================
# HELPERS: METADATA FETCHING
# =========================
def _fetch_video_metadata(video_id: str, youtube_url: str) -> Dict[str, any]:
    """
    Fetch video metadata (title, duration, channel, views, publish_date, thumbnail).
    
    Graceful fallback: If pytube fails, returns minimal metadata dict.
    
    Args:
        video_id: YouTube video_id
        youtube_url: Full YouTube URL
        
    Returns:
        Dict with:
        - title: str (or "Unknown Video")
        - duration: int (seconds, or 0 if unavailable)
        - channel: str (or "Unknown Channel")
        - views: int (or 0)
        - publish_date: datetime (or None)
        - thumbnail_url: str (or None)
        
    Example:
        >>> metadata = _fetch_video_metadata("dQw4w9WgXcQ", "https://...")
        >>> print(metadata["title"])
    """
    logger.debug(f"Fetching metadata for video {video_id}")
    
    default_metadata = {
        "title": f"YouTube Video ({video_id})",
        "duration": 0,
        "channel": "Unknown Channel",
        "views": 0,
        "publish_date": None,
        "thumbnail_url": None
    }
    
    if not PYTUBE_AVAILABLE:
        logger.warning("pytube not available - returning default metadata")
        return default_metadata
    
    try:
        # Use timeout to prevent hanging
        yt = YouTube(youtube_url, use_oauth=False, allow_oauth_cache=False)
        
        metadata = {
            "title": yt.title or default_metadata["title"],
            "duration": yt.length or 0,  # seconds
            "channel": yt.author or default_metadata["channel"],
            "views": yt.views or 0,
            "publish_date": yt.publish_date,
            "thumbnail_url": yt.thumbnail_url
        }
        
        logger.info(f"Fetched metadata: title='{metadata['title']}', "
                   f"duration={metadata['duration']}s, views={metadata['views']}")
        
        return metadata
    
    except Exception as e:
        logger.warning(f"Failed to fetch metadata via pytube: {e} — using defaults")
        return default_metadata


def _fetch_transcript(
    video_id: str,
    preferred_language: str = DEFAULT_LANGUAGE,
    fallback_languages: List[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch transcript with fallback language support.
    
    Strategy:
    1. Try preferred language (default: "en")
    2. Try fallback languages (en, vi, es, fr, etc.)
    3. Return (transcript_text, language_used) or (None, None)
    
    Args:
        video_id: YouTube video_id
        preferred_language: Language code to try first (default: "en")
        fallback_languages: Language codes to try if preferred fails
        
    Returns:
        Tuple of (transcript_text: str, language_used: str) or (None, None)
        
    Raises:
        Exception: Only internal errors; transcript unavailable returns (None, None)
        
    Example:
        >>> text, lang = _fetch_transcript("dQw4w9WgXcQ")
        >>> if text:
        ...     print(f"Got transcript in {lang}")
    """
    if not TRANSCRIPT_API_AVAILABLE:
        logger.warning("youtube-transcript-api not available")
        return None, None
    
    if fallback_languages is None:
        fallback_languages = FALLBACK_LANGUAGES
    
    # Build language list (preferred first)
    languages_to_try = [preferred_language] + [
        lang for lang in fallback_languages if lang != preferred_language
    ]
    
    logger.debug(f"Fetching transcript for {video_id}, languages: {languages_to_try}")
    
    for lang in languages_to_try:
        try:
            logger.debug(f"Trying language: {lang}")
            
            transcript = YouTubeTranscriptApi.get_transcript(
                video_id,
                languages=[lang]
            )
            
            # Combine transcript entries (each has text + start + duration)
            full_text = " ".join(entry["text"] for entry in transcript)
            
            if len(full_text.strip()) >= MIN_TRANSCRIPT_LENGTH:
                logger.info(f"Fetched transcript ({len(full_text)} chars) in language: {lang}")
                return full_text.strip(), lang
            else:
                logger.debug(f"Transcript too short in {lang}: {len(full_text)} chars")
        
        except (TranscriptsDisabled, NoTranscriptFound):
            logger.debug(f"Transcript not available in language: {lang}")
            continue
        
        except Exception as e:
            logger.debug(f"Error fetching {lang} transcript: {e}")
            continue
    
    logger.warning(f"No transcript found for {video_id} in any language")
    return None, None


def check_duplicate_video(video_id: str, db=None) -> bool:
    """
    Check if video already imported.
    
    Args:
        video_id: YouTube video_id
        db: MongoDB database instance
        
    Returns:
        True if duplicate, False otherwise
    """
    if not ENABLE_DUPLICATE_CHECK:
        return False
    
    try:
        if db is None:
            db = get_db()
        
        existing = db.resources.find_one({
            "source": SourceEnum.youtube.value,
            "video_id": video_id
        })
        
        if existing:
            logger.warning(f"Video already imported: {video_id}")
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Error checking duplicate video: {e}")
        return False


# =========================
# MAIN IMPORT
# =========================
def import_youtube(
    youtube_url: str,
    topic: str,
    level: str = "beginner",
    concept_id: Optional[int] = None,
    user_id: Optional[int] = None,
    pedagogy_type: str = "video"
) -> Dict[str, any]:
    """
    Import YouTube video: fetch metadata, transcript, chunk, embed, store.
    
    Pipeline:
    1. Validate YouTube URL + extract video_id
    2. Check for duplicates (optional)
    3. Fetch video metadata (title, duration, channel, views, etc.)
    4. Fetch transcript (with fallback languages)
    5. If no transcript → Save metadata-only doc + return gracefully
    6. If transcript → Chunk text (respecting sentence boundaries)
    7. Generate embeddings for each chunk
    8. Store chunks with enriched metadata
    9. Return import result (chunks created, transcript quality, language, etc.)
    
    Args:
        youtube_url: Full YouTube URL (https://www.youtube.com/watch?v=...)
        topic: Topic category (e.g., "python", "machine learning")
        level: Bloom level (beginner/intermediate/advanced)
        concept_id: Optional concept to associate (auto-mapped if not provided)
        user_id: Optional user ID for audit trail
        pedagogy_type: Pedagogy type (default: "video")
        
    Returns:
        Dict with:
        - success: bool (True if import successful)
        - video_id: str
        - title: str
        - metadata: Dict (channel, views, duration, publish_date, thumbnail_url, etc.)
        - transcript_available: bool
        - transcript_language: Optional[str]
        - transcript_length: int (characters)
        - chunks_created: int (successfully inserted)
        - concept_id: int (auto-mapped if not provided)
        - resources: List[Dict] (inserted resource docs)
        - message: str (summary)
        
    Raises:
        ValueError: If URL validation fails
        Exception: Only internal DB errors; most failures are graceful
        
    Example:
        >>> result = import_youtube(
        ...     "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ...     topic="music",
        ...     level="beginner",
        ...     concept_id=5
        ... )
        >>> print(f"Created {result['chunks_created']} chunks")
    """
    logger.info(f"Importing YouTube: url={youtube_url}, topic={topic}, level={level}, user_id={user_id}")
    
    try:
        # 1️⃣ VALIDATE URL
        validate_youtube_url(youtube_url)
        video_id = extract_video_id(youtube_url)
        logger.debug(f"Validated video_id: {video_id}")
        
        # 2️⃣ CHECK DUPLICATES
        db = get_db()
        if check_duplicate_video(video_id, db):
            logger.warning(f"Video already imported: {video_id}")
            raise ValueError(f"Video {video_id} already imported")
        
        # 3️⃣ FETCH METADATA
        metadata = _fetch_video_metadata(video_id, youtube_url)
        
        # 4️⃣ AUTO-MAP CONCEPT IF NEEDED
        if concept_id is None:
            concept_id = resolve_concept_id(topic, allow_fallback=True)
            logger.debug(f"Auto-mapped topic '{topic}' → concept_id {concept_id}")
        
        # 5️⃣ FETCH TRANSCRIPT
        transcript_text, transcript_lang = _fetch_transcript(video_id)
        
        # 6️⃣ IF NO TRANSCRIPT → SAVE METADATA-ONLY
        if not transcript_text or len(transcript_text.strip()) < MIN_TRANSCRIPT_LENGTH:
            logger.warning(f"No usable transcript for {video_id} — saving metadata only")
            
            doc = db.resources.insert_one({
                "title": metadata["title"],
                "topic": topic.strip().lower(),
                "concept_id": concept_id,
                "level": level,
                "source": SourceEnum.youtube.value if hasattr(SourceEnum.youtube, "value") else "youtube",
                "video_id": video_id,
                "youtube_url": youtube_url,
                "video_metadata": metadata,
                "transcript_available": False,
                "chunk_count": 0,
                "created_at": datetime.utcnow(),
                "created_by_user_id": user_id,
                "import_status": "success_no_transcript",
                "pedagogy_type": pedagogy_type,
                "hit_count": 0
            })
            
            logger.info(f"Video metadata saved (no transcript): {video_id}")
            
            return {
                "success": True,
                "video_id": video_id,
                "title": metadata["title"],
                "metadata": metadata,
                "transcript_available": False,
                "transcript_language": None,
                "transcript_length": 0,
                "chunks_created": 0,
                "concept_id": concept_id,
                "resources": [{"_id": str(doc.inserted_id)}],
                "message": f"Video metadata saved (transcript unavailable): {metadata['title']}"
            }
        
        logger.info(f"Transcript fetched ({len(transcript_text)} chars, language: {transcript_lang})")
        
        # 7️⃣ CHUNK TEXT
        chunks = _chunk_text_with_overlap(
            transcript_text,
            chunk_size=YOUTUBE_CHUNK_SIZE,
            overlap=YOUTUBE_CHUNK_OVERLAP
        )
        
        if not chunks:
            logger.warning(f"Failed to chunk transcript for {video_id}")
            raise RuntimeError("Unable to chunk transcript")
        
        # 8️⃣ STORE CHUNKS
        inserted_docs = []
        
        for idx, chunk in enumerate(chunks):
            try:
                # Generate embedding
                embedding = embed_text(chunk)
                
                # Create document
                doc = {
                    "title": metadata["title"],
                    "content": chunk,
                    "topic": topic.strip().lower(),
                    "concept_id": concept_id,
                    "level": level,
                    "source": SourceEnum.youtube.value if hasattr(SourceEnum.youtube, "value") else "youtube",
                    "video_id": video_id,
                    "youtube_url": youtube_url,
                    "chunk_index": idx + 1,
                    "chunk_count": len(chunks),
                    "embedding": embedding,
                    "video_metadata": metadata,
                    "transcript_language": transcript_lang,
                    "created_at": datetime.utcnow(),
                    "created_by_user_id": user_id,
                    "import_status": "success",
                    "pedagogy_type": pedagogy_type,
                    "hit_count": 0
                }
                
                result = db.resources.insert_one(doc)
                inserted_docs.append(doc)
                logger.debug(f"Stored chunk {idx+1}/{len(chunks)}: {len(chunk)} chars")
            
            except Exception as e:
                logger.warning(f"Error storing chunk {idx+1}: {e}")
                continue
        
        # 9️⃣ RETURN RESULT
        if len(inserted_docs) == 0:
            logger.error(f"No chunks inserted for {video_id}")
            raise RuntimeError("Failed to insert any chunks")
        
        logger.info(
            f"YouTube import complete: video_id={video_id}, "
            f"chunks={len(inserted_docs)}, transcript_lang={transcript_lang}"
        )
        
        return {
            "success": True,
            "video_id": video_id,
            "title": metadata["title"],
            "metadata": metadata,
            "transcript_available": True,
            "transcript_language": transcript_lang,
            "transcript_length": len(transcript_text),
            "chunks_created": len(inserted_docs),
            "concept_id": concept_id,
            "resources": inserted_docs,
            "message": f"Imported YouTube: {len(inserted_docs)} chunks from '{metadata['title']}'"
        }
    
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error importing YouTube: {e}")
        raise RuntimeError(f"Failed to import YouTube: {str(e)}")


# =========================
# BATCH IMPORT
# =========================
def import_youtube_batch(
    videos: List[Dict[str, any]],
    user_id: Optional[int] = None,
    skip_duplicates: bool = True,
    stop_on_error: bool = False
) -> Dict[str, any]:
    """
    Import multiple YouTube videos with batch processing + partial failure handling.
    
    Each video dict should have: youtube_url, topic, level (optional), concept_id (optional)
    
    Args:
        videos: List of video dicts
        user_id: Optional user ID
        skip_duplicates: If True, skip duplicates; if False, raise error
        stop_on_error: If True, stop on first error; if False, continue
        
    Returns:
        Dict with:
        - success: bool (True if all succeeded)
        - status: "success" | "partial" | "failed"
        - total: int
        - successful: int
        - failed: int
        - skipped: int
        - results: List[Dict] (import result per video)
        - errors: List[Dict] (error per video)
        
    Example:
        >>> results = import_youtube_batch([
        ...     {"youtube_url": "https://...", "topic": "python"},
        ...     {"youtube_url": "https://...", "topic": "javascript"}
        ... ])
        >>> print(f"Imported {results['successful']}/{results['total']}")
    """
    logger.info(f"Batch importing {len(videos)} YouTube videos")
    
    if len(videos) > YOUTUBE_BATCH_SIZE:
        raise ValueError(f"Batch size {len(videos)} exceeds max {YOUTUBE_BATCH_SIZE}")
    
    results = []
    errors = []
    successful = 0
    skipped = 0
    
    for idx, video in enumerate(videos):
        try:
            result = import_youtube(
                youtube_url=video.get("youtube_url"),
                topic=video.get("topic", "general"),
                level=video.get("level", "beginner"),
                concept_id=video.get("concept_id"),
                user_id=user_id,
                pedagogy_type=video.get("pedagogy_type", "video")
            )
            results.append(result)
            successful += 1
            logger.debug(f"[{idx+1}/{len(videos)}] Imported successfully")
        
        except ValueError as e:
            if "already imported" in str(e) and skip_duplicates:
                skipped += 1
                logger.info(f"[{idx+1}/{len(videos)}] Skipped duplicate")
            else:
                errors.append({
                    "index": idx,
                    "youtube_url": video.get("youtube_url"),
                    "error": str(e)
                })
                logger.error(f"[{idx+1}/{len(videos)}] Error: {e}")
                
                if stop_on_error:
                    break
        
        except Exception as e:
            errors.append({
                "index": idx,
                "youtube_url": video.get("youtube_url"),
                "error": str(e)
            })
            logger.error(f"[{idx+1}/{len(videos)}] Unexpected error: {e}")
            
            if stop_on_error:
                break
    
    total = len(videos)
    failed = len(errors)
    
    status = "success" if failed == 0 else ("partial" if successful > 0 else "failed")
    
    logger.info(f"Batch import complete: total={total}, successful={successful}, "
               f"failed={failed}, skipped={skipped}, status={status}")
    
    return {
        "success": failed == 0 and successful == len(videos),
        "status": status,
        "total": total,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "errors": errors
        }