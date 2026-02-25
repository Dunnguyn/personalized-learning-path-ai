from typing import List, Dict, Optional, Tuple
import logging
import re
import os
from pathlib import Path
from functools import lru_cache

from backend.app.services.embedding_service import store_resource, store_resources_batch, store_embedding_only, store_embedding_only
from backend.app.database.mongo import db

logger = logging.getLogger(__name__)

# ==================================================
# CONFIG
# ==================================================
MAX_PDF_SIZE = int(os.getenv("MAX_PDF_SIZE_MB", "50")) * 1024 * 1024
CHUNK_SIZE = int(os.getenv("PDF_CHUNK_SIZE", "2000"))  # Increased from 500 to reduce chunk count
CHUNK_OVERLAP = int(os.getenv("PDF_CHUNK_OVERLAP", "200"))  # Increased proportionally
MIN_CHUNK_LENGTH = int(os.getenv("PDF_MIN_CHUNK_LENGTH", "100"))  # Increased minimum
MIN_RELEVANCE_RATIO = float(os.getenv("PDF_MIN_RELEVANCE_RATIO", "0.3"))
MAX_CHUNKS = int(os.getenv("PDF_MAX_CHUNKS", "100"))  # Limit max chunks to prevent timeout

# Try PyMuPDF (fitz) first, fallback to pypdf
try:
    import fitz
    USE_PYMUPDF = True
    logger.info("Using PyMuPDF for PDF extraction")
except ImportError:
    USE_PYMUPDF = False
    from pypdf import PdfReader
    logger.info("PyMuPDF not available; using pypdf")


# ==================================================
# KEYWORD MANAGEMENT
# ==================================================
@lru_cache(maxsize=128)
def _get_topic_keywords(topic: str) -> List[str]:
    """
    Get domain-specific keywords for filtering PDF chunks.
    Cached for performance.
    """
    if not topic:
        return []
    
    topic_lower = topic.lower()
    
    # Predefined keyword maps
    keyword_maps = {
        "python": [
            "list", "dict", "tuple", "set", "string",
            "loop", "for", "while", "function", "def", "class",
            "append", "pop", "index", "keys", "values",
            "import", "module", "package", "variable", "assignment"
        ],
        "fastapi": [
            "fastapi", "endpoint", "router", "api",
            "request", "response", "http", "get", "post", "put", "delete",
            "async", "await", "dependency", "validation", "pydantic"
        ],
        "javascript": [
            "javascript", "js", "function", "const", "let", "var",
            "array", "object", "promise", "async", "await",
            "react", "vue", "angular", "dom", "event"
        ],
        "database": [
            "database", "sql", "query", "table", "schema",
            "index", "join", "select", "insert", "update", "delete",
            "mongodb", "mysql", "postgres", "redis"
        ],
        "machine learning": [
            "machine learning", "deep learning", "neural", "model",
            "training", "dataset", "algorithm", "classification", "regression",
            "tensorflow", "pytorch", "scikit-learn", "accuracy", "precision"
        ],
    }
    
    # Try exact match
    for key, keywords in keyword_maps.items():
        if key == topic_lower:
            logger.debug(f"Found exact keyword set for topic: {topic}")
            return keywords
    
    # Try substring match
    for key, keywords in keyword_maps.items():
        if key in topic_lower or topic_lower in key:
            logger.debug(f"Found substring keyword set for topic: {topic}")
            return keywords
    
    # Fallback: extract words from topic as keywords
    fallback = [w for w in re.split(r"\W+", topic_lower) if len(w) > 3]
    logger.debug(f"Using fallback keywords for topic '{topic}': {fallback}")
    return fallback


# ==================================================
# TEXT CHUNKING (improved)
# ==================================================
def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    min_length: int = MIN_CHUNK_LENGTH
) -> List[str]:
    """
    Split text into overlapping chunks, respecting sentence boundaries
    to avoid mid-sentence cuts.
    
    Parameters
    ----------
    text : str
        Text to chunk
    chunk_size : int
        Target chunk size (characters)
    overlap : int
        Overlap between chunks
    min_length : int
        Minimum chunk length to include
    
    Returns
    -------
    List[str] : chunks
    """
    if not text:
        return []
    
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        # Try to get chunk_size characters
        end = min(start + chunk_size, text_len)
        
        # If we're not at the end, try to cut at sentence boundary
        if end < text_len:
            # Look for sentence terminator before end
            sentence_cutoff = max(
                text.rfind(". ", start, end),
                text.rfind("? ", start, end),
                text.rfind("! ", start, end),
                text.rfind("\n\n", start, end)
            )
            
            if sentence_cutoff > start:
                end = sentence_cutoff + 1
        
        chunk = text[start:end].strip()
        
        # Only keep non-empty chunks
        if len(chunk) >= min_length:
            chunks.append(chunk)
        
        # Move start forward (with overlap)
        start = end - overlap
        if start <= 0:
            start = end
        
        # Prevent infinite loop: once we've processed to the end, stop
        if end >= text_len:
            break
    
    logger.debug(f"Chunked text into {len(chunks)} chunks (size={chunk_size}, overlap={overlap})")
    return chunks


# ==================================================
# RELEVANCE SCORING
# ==================================================
def _score_chunk_relevance(
    chunk: str,
    keywords: List[str],
    min_ratio: float = MIN_RELEVANCE_RATIO
) -> float:
    """
    Score chunk relevance (0.0 - 1.0) based on keyword matches.
    Returns score >= min_ratio.
    """
    if not keywords:
        return 1.0  # No keywords = accept all
    
    chunk_lower = chunk.lower()
    matches = sum(1 for kw in keywords if kw in chunk_lower)
    
    max_possible = len(keywords)
    score = matches / max_possible if max_possible > 0 else 0
    
    return score


def _is_relevant_chunk(
    chunk: str,
    keywords: List[str],
    min_ratio: float = MIN_RELEVANCE_RATIO
) -> bool:
    """Check if chunk meets relevance threshold."""
    return _score_chunk_relevance(chunk, keywords, min_ratio) >= min_ratio


# ==================================================
# CONTEXT INJECTION
# ==================================================
def _inject_context(
    chunk: str,
    topic: str,
    level: str,
    page_num: Optional[int] = None
) -> str:
    """
    Inject learning context metadata to reduce hallucination.
    """
    context = f"[Learning Material]\nTopic: {topic}\nLevel: {level}"
    if page_num:
        context += f"\nPage: {page_num}"
    context += "\n\n"
    
    return context + chunk


# ==================================================
# PDF EXTRACTION (PyMuPDF or pypdf)
# ==================================================
def _extract_text_from_pdf(file_path: str) -> Tuple[str, int]:
    """
    Extract text from PDF using best available library.
    Returns (text, page_count) or raises Exception.
    """
    file_path = str(file_path)
    logger.debug(f"_extract_text_from_pdf: file_path={file_path}")
    
    if USE_PYMUPDF:
        try:
            logger.debug(f"  Opening PDF with PyMuPDF")
            doc = fitz.open(file_path)
            full_text = ""
            
            for page_num, page in enumerate(doc, start=1):
                try:
                    text = page.get_text()
                    if text:
                        full_text += f"\n[Page {page_num}]\n{text}"
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num}: {e}")
                    continue
            
            page_count = len(doc)
            doc.close()
            
            logger.debug(f"  Extraction complete: pages={page_count}, chars={len(full_text)}")
            return full_text.strip(), page_count
        except Exception as e:
            logger.exception(f"PyMuPDF extraction failed: {e}")
            raise
    else:
        try:
            logger.debug(f"  Opening PDF with pypdf")
            reader = PdfReader(file_path)
            full_text = ""
            
            for page_num, page in enumerate(reader.pages, start=1):
                try:
                    text = page.extract_text()
                    if text:
                        full_text += f"\n[Page {page_num}]\n{text}"
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num}: {e}")
                    continue
            
            page_count = len(reader.pages)
            
            logger.debug(f"  Extraction complete: pages={page_count}, chars={len(full_text)}")
            return full_text.strip(), page_count
        except Exception as e:
            logger.exception(f"pypdf extraction failed: {e}")
            raise


def _generate_pdf_thumbnail(file_path: str) -> Optional[str]:
    """
    Generate a thumbnail (base64-encoded image) of the first page of a PDF.
    Uses PyMuPDF if available.
    
    Returns base64 string of PNG image, or None if failed.
    """
    if not USE_PYMUPDF:
        logger.debug("PyMuPDF not available, skipping thumbnail generation")
        return None
    
    try:
        import base64
        doc = fitz.open(file_path)
        if len(doc) == 0:
            return None
        
        # Render first page to image (300 DPI)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image_data = pix.tobytes("png")
        doc.close()
        
        # Encode as base64
        b64_str = base64.b64encode(image_data).decode('utf-8')
        logger.debug(f"Generated PDF thumbnail: {len(b64_str)} bytes")
        return f"data:image/png;base64,{b64_str}"
    except Exception as e:
        logger.warning(f"Failed to generate PDF thumbnail: {e}")
        return None


# ==================================================
# MAIN IMPORT FUNCTION
# ==================================================
def import_pdf(
    file_path: str,
    topic: str,
    level: str = "beginner",
    concept_id: Optional[int] = None,
    min_relevance: float = MIN_RELEVANCE_RATIO
) -> Dict:
    """
    Import PDF into RAG system.
    
    Pipeline:
    1. Validate input
    2. Extract text from PDF (handle scanned PDFs gracefully)
    3. Chunk text with sentence boundary awareness
    4. Filter by topic relevance
    5. Inject context metadata
    6. Store with embeddings
    
    Parameters
    ----------
    file_path : str
        Path to PDF file
    topic : str
        Learning topic
    level : str
        Difficulty level
    concept_id : int
        Associated concept ID (optional)
    min_relevance : float
        Minimum relevance ratio [0, 1]
    
    Returns
    -------
    Dict : import results
    """
    
    logger.info(f"Importing PDF: {file_path}, topic={topic}, level={level}")
    
    try:
        # ---------- VALIDATE INPUT ----------
        if not file_path or not topic:
            raise ValueError("file_path and topic are required")
        
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        if not file_path.suffix.lower() == ".pdf":
            raise ValueError(f"File is not a PDF: {file_path.suffix}")
        
        file_size = file_path.stat().st_size
        if file_size > MAX_PDF_SIZE:
            raise ValueError(f"PDF too large: {file_size} bytes (max {MAX_PDF_SIZE})")
        
        logger.debug(f"Validated PDF: size={file_size} bytes")
        
        # ---------- EXTRACT TEXT ----------
        try:
            full_text, page_count = _extract_text_from_pdf(str(file_path))
        except Exception as e:
            logger.error(f"PDF text extraction failed: {e}")
            # Return graceful error instead of crashing
            return {
                "file": str(file_path),
                "error": "Could not extract text from PDF",
                "detail": str(e),
                "total_chunks": 0,
                "inserted_chunks": 0,
                "skipped_chunks": 0,
                "reason": "scanned_or_corrupted"
            }
        
        if not full_text:
            logger.warning(f"PDF has no extractable text: {file_path}")
            return {
                "file": str(file_path),
                "error": "PDF contains no readable text",
                "detail": "Possibly a scanned image or corrupted file",
                "total_chunks": 0,
                "inserted_chunks": 0,
                "skipped_chunks": 0,
                "reason": "no_readable_text"
            }
        
        logger.info(f"Extracted {page_count} pages, {len(full_text)} chars from PDF")
        
        # ---------- GENERATE THUMBNAIL ----------
        thumbnail = _generate_pdf_thumbnail(str(file_path))
        logger.info(f"PDF thumbnail generated: {'yes' if thumbnail else 'no'}")
        
        # ---------- CREATE SINGLE MAIN RESOURCE ----------
        # Create a summary or take first 1000 characters for main resource
        summary = full_text[:1000].strip() + "..." if len(full_text) > 1000 else full_text.strip()
        
        main_resource = store_resource(
            title=file_path.name,
            content=summary,
            topic=topic,
            level=level,
            source="pdf",
            concept_id=concept_id,
            url=None,
            pedagogy_type="text",
            bloom_level="understand",
            thumbnail=thumbnail,
            pdf_file_path=str(file_path)
        )
        
        resource_id = main_resource.get("resource_id")
        logger.info(f"Created main resource: {resource_id} for PDF: {file_path.name}")
        
        # ---------- CHUNK TEXT ----------
        logger.debug(f"Chunking text with size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}")
        chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        logger.info(f"Generated {len(chunks)} chunks from PDF")
        
        if not chunks and full_text.strip():
            # Fallback: keep whole text as a single chunk when content is too short
            chunks = [full_text.strip()]
            logger.info("Chunk fallback: using full text as a single chunk")

        if not chunks:
            logger.warning(f"No valid chunks generated from PDF: {file_path}")
            return {
                "file": str(file_path),
                "error": "PDF contains no valid chunks",
                "detail": "Could not chunk text into segments",
                "total_chunks": 0,
                "inserted_chunks": 0,
                "skipped_chunks": 0
            }
        
        logger.info(f"Total chunks to process: {len(chunks)}")
        
        logger.info(f"Generated {len(chunks)} chunks from {len(full_text)} chars (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")
        
        # Limit chunks to prevent timeout on very large PDFs
        if len(chunks) > MAX_CHUNKS:
            logger.warning(f"PDF generated {len(chunks)} chunks, limiting to {MAX_CHUNKS} to prevent timeout")
            chunks = chunks[:MAX_CHUNKS]
        
        # ---------- FILTER & PROCESS CHUNKS ----------
        keywords = _get_topic_keywords(topic)
        inserted = 0
        skipped = 0
        store_errors = []
        
        logger.info(f"Processing {len(chunks)} chunks for relevance (keywords={len(keywords)} for topic={topic})")
        logger.info(f"First chunk preview: {chunks[0][:200]}..." if chunks else "No chunks to process")
        
        # Wrap entire processing in try-catch to prevent crashes
        try:
            for idx, chunk in enumerate(chunks):
                try:
                    # Progress logging
                    if idx > 0 and idx % 10 == 0:
                        logger.info(f"Progress: {idx}/{len(chunks)} chunks processed ({inserted} inserted, {skipped} skipped)")
                    
                    # Relevance check
                    relevant = _is_relevant_chunk(chunk, keywords, min_relevance)
                    if not relevant:
                        skipped += 1
                        logger.debug(f"Chunk {idx} skipped: failed relevance check")
                        continue
                    
                    logger.debug(f"Chunk {idx} passed relevance check, storing embedding...")
                    
                    # Inject context
                    content = _inject_context(chunk, topic, level, page_num=None)
                    
                    # Store as embedding only (not a visible resource)
                    embedding_id = store_embedding_only(
                        content=content,
                        parent_resource_id=resource_id,
                        chunk_index=idx,
                        topic=topic,
                        level=level,
                        metadata={"filename": file_path.name}
                    )
                    logger.debug(f"Stored chunk {idx} with embedding_id: {embedding_id}")
                    
                    inserted += 1
                
                except Exception as e:
                    logger.exception(f"Error storing chunk {idx}/{len(chunks)}: {type(e).__name__}: {e}")
                    store_errors.append(f"Chunk {idx}: {str(e)}")
                    skipped += 1
                    continue
        except Exception as e:
            logger.exception(f"Critical error during chunk processing: {e}")
            if inserted > 0:
                logger.warning(f"Partial success: {inserted} chunks were inserted before error")
                # Continue with partial success
            else:
                raise RuntimeError(f"PDF processing failed completely: {str(e)}")

        logger.info(f"Relevance filter pass 1: {inserted} inserted, {skipped} skipped of {len(chunks)} total")

        if inserted == 0 and chunks and keywords:
            logger.info("No chunks inserted with relevance filter; retrying without filter")
            skipped = 0
            for idx, chunk in enumerate(chunks):
                try:
                    content = _inject_context(chunk, topic, level, page_num=None)
                    store_embedding_only(
                        content=content,
                        parent_resource_id=resource_id,
                        chunk_index=idx,
                        topic=topic,
                        level=level,
                        metadata={"filename": file_path.name}
                    )
                    inserted += 1
                except Exception as e:
                    logger.exception(f"Error in fallback chunk {idx}/{len(chunks)}: {type(e).__name__}: {e}")
                    store_errors.append(f"Fallback chunk {idx}: {str(e)}")
                    skipped += 1
                    continue
            logger.info(f"Relevance filter pass 2 (no keywords): {inserted} inserted, {skipped} skipped of {len(chunks)} total")
        
        if inserted == 0:
            error_detail = "; ".join(store_errors[:5]) if store_errors else "Unknown error during chunk storage"
            logger.error(f"CRITICAL: Failed to insert ANY chunks from PDF. Total errors: {len(store_errors)}. Sample: {error_detail}")
            raise RuntimeError(f"PDF chunk storage failed: {error_detail}")
        
        logger.info(
            f"PDF import complete: file={file_path.name}, "
            f"inserted={inserted}, skipped={skipped} chunks, "
            f"pages={page_count}"
        )
        
        # ---------- RESULT ----------
        return {
            "success": True,
            "file": str(file_path),
            "file_name": file_path.name,
            "file_size_bytes": file_size,
            "pages": page_count,
            "total_chars": len(full_text),
            "total_chunks": len(chunks),
            "inserted_chunks": inserted,
            "skipped_chunks": skipped,
            "topic": topic,
            "level": level,
            "concept_id": concept_id,
            "message": f"Successfully imported {inserted} chunks from PDF"
        }
    
    except ValueError as e:
        logger.warning(f"Validation error in import_pdf: {e}")
        return {
            "success": False,
            "file": str(file_path),
            "error": str(e),
            "total_chunks": 0,
            "inserted_chunks": 0,
            "skipped_chunks": 0
        }
    except Exception as e:
        logger.exception(f"Unexpected error in import_pdf: {type(e).__name__}: {e}")
        error_type = type(e).__name__
        error_msg = str(e)
        return {
            "success": False,
            "file": str(file_path),
            "error": f"{error_type}: {error_msg}",
            "detail": error_msg,
            "total_chunks": 0,
            "inserted_chunks": 0,
            "skipped_chunks": 0
        }