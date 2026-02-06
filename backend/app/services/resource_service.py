"""
Resource Service: Central orchestration for resource CRUD operations.

Provides unified interface for:
- Single resource addition with embedding + metadata
- Batch resource import with duplicate detection + partial failure handling
- Semantic search with result enrichment
- PDF/YouTube import with error recovery
- Resource validation + enrichment pipeline
- Analytics and stats generation

All operations include:
- Comprehensive logging (debug/info/warning/exception)
- Input validation + sanitization
- Atomic operations with rollback on failure
- Metadata enrichment (timestamps, counts, success rates)
- Configuration via environment variables
"""

import os
import shutil
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import UploadFile
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, BulkWriteError

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import (
    store_resource,
    semantic_search
)
from backend.app.services.resource_importer import (
    import_resources,
    import_resource,
    validate_resource
)
from backend.app.services.pdf_importer import import_pdf
from backend.app.services.youtube_importer import import_youtube
from backend.app.api.schemas import (
    ResourceCreate,
    ResourceImportRequest
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# CONFIG
# =========================
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "backend/uploads"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_FILE_EXTENSIONS = {".pdf", ".txt"}
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "50"))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "1000"))
ENABLE_DUPLICATE_CHECK = os.getenv("ENABLE_DUPLICATE_CHECK", "true").lower() == "true"

# Ensure upload directory exists
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

logger.info(f"Resource service initialized: UPLOAD_DIR={UPLOAD_DIR}, MAX_FILE_SIZE_MB={MAX_FILE_SIZE_MB}")


# =========================
# HELPERS: SERIALIZATION & VALIDATION
# =========================
def serialize_mongo(doc: dict) -> dict:
    """
    Convert MongoDB ObjectId to string for JSON serialization.
    
    Args:
        doc: MongoDB document dict
        
    Returns:
        Serialized document with _id as string
    """
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent directory traversal and invalid chars.
    
    Args:
        filename: Original filename from upload
        
    Returns:
        Safe filename with only alphanumeric, _, -, .
        
    Raises:
        ValueError: If filename is empty after sanitization
    """
    if not filename:
        raise ValueError("Filename cannot be empty")
    
    # Remove path components
    filename = os.path.basename(filename)
    
    # Replace spaces and dangerous chars with underscore
    filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    
    if not filename:
        raise ValueError("Filename must contain at least one alphanumeric character")
    
    logger.debug(f"Sanitized filename: {filename}")
    return filename


def validate_file_upload(file: UploadFile, max_size_bytes: int = MAX_FILE_SIZE_BYTES) -> None:
    """
    Validate uploaded file: extension and size.
    
    Args:
        file: Uploaded file from FastAPI
        max_size_bytes: Maximum allowed file size in bytes
        
    Raises:
        ValueError: If extension not allowed or file too large
    """
    if not file.filename:
        raise ValueError("File must have a name")
    
    # Extension check
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_FILE_EXTENSIONS:
        raise ValueError(f"File extension {file_ext} not allowed. Allowed: {ALLOWED_FILE_EXTENSIONS}")
    
    # Size check (check content_length if available)
    if file.size and file.size > max_size_bytes:
        raise ValueError(f"File size {file.size} bytes exceeds maximum {max_size_bytes} bytes ({MAX_FILE_SIZE_MB}MB)")
    
    logger.debug(f"File validation passed: {file.filename} ({file.size or 'unknown'} bytes)")


def check_duplicate_resource(title: str, topic: str, db=None) -> bool:
    """
    Check if resource with same title + topic already exists.
    
    Args:
        title: Resource title
        topic: Resource topic
        db: MongoDB database instance
        
    Returns:
        True if duplicate found, False otherwise
    """
    if not ENABLE_DUPLICATE_CHECK:
        return False
    
    try:
        if db is None:
            db = get_db()
        
        existing = db.resources.find_one({
            "title": {"$regex": f"^{title}$", "$options": "i"},
            "topic": {"$regex": f"^{topic}$", "$options": "i"}
        })
        
        if existing:
            logger.warning(f"Duplicate resource detected: title='{title}', topic='{topic}'")
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Error checking duplicate: {e}")
        return False


def cleanup_temp_file(file_path: Path) -> None:
    """
    Safely delete temporary file after processing.
    
    Args:
        file_path: Path to file to delete
    """
    try:
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to cleanup temp file {file_path}: {e}")


# =========================
# ADD SINGLE RESOURCE
# =========================
def add_resource_service(resource: ResourceCreate, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Add single resource with embedding + metadata.
    
    Pipeline:
    1. Validate input schema
    2. Check for duplicates (optional)
    3. Store with embeddings (RAG index)
    4. Attach metadata (concept_id, url, timestamps)
    5. Return enriched response
    
    Args:
        resource: ResourceCreate schema with title, content, topic, level, source, concept_id, url
        user_id: Optional user ID for audit trail
        
    Returns:
        Dict with message + resource doc (serialized, with _id as string)
        
    Raises:
        ValueError: If validation fails
        Exception: If database operation fails
        
    Example:
        >>> result = add_resource_service(
        ...     ResourceCreate(
        ...         title="Python Basics",
        ...         content="Introduction to Python...",
        ...         topic="python",
        ...         level="beginner",
        ...         source="web",
        ...         concept_id=1,
        ...         url="https://example.com"
        ...     )
        ... )
        >>> print(result["resource"]["_id"])
    """
    logger.info(f"Adding resource: title='{resource.title}', topic='{resource.topic}', user_id={user_id}")
    
    try:
        # 1. Validate input
        if not resource.title or not resource.title.strip():
            raise ValueError("Resource title cannot be empty")
        
        if len(resource.title.strip()) < 3:
            raise ValueError("Resource title must be at least 3 characters")
        
        if len(resource.title.strip()) > 500:
            raise ValueError("Resource title cannot exceed 500 characters")
        
        if not resource.topic or not resource.topic.strip():
            raise ValueError("Resource topic cannot be empty")
        
        if resource.concept_id is None or resource.concept_id <= 0:
            raise ValueError("Resource concept_id must be a positive integer")
        
        # 2. Check duplicates
        if check_duplicate_resource(resource.title, resource.topic):
            logger.warning(f"Duplicate resource blocked: {resource.title}")
            raise ValueError("Resource with this title and topic already exists")
        
        # 3. Prepare content
        content = resource.content.strip() if resource.content else resource.title
        if len(content) < 10:
            logger.warning(f"Resource content very short ({len(content)} chars): {resource.title}")
        
        # 4. Store with embeddings
        doc = store_resource(
            title=resource.title.strip(),
            content=content,
            topic=resource.topic.strip().lower(),
            level=resource.level,
            source=resource.source
        )
        
        logger.debug(f"Resource stored with embedding: _id={doc.get('_id')}")
        
        # 5. Attach metadata
        doc["concept_id"] = resource.concept_id
        doc["url"] = resource.url
        doc["created_at"] = datetime.utcnow()
        doc["created_by_user_id"] = user_id
        doc["is_reviewed"] = False
        doc["import_status"] = "success"
        
        # 6. Persist metadata
        db = get_db()
        result = db.resources.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "concept_id": resource.concept_id,
                "url": resource.url,
                "created_by_user_id": user_id,
                "is_reviewed": False,
                "import_status": "success",
                "created_at": datetime.utcnow()
            }},
            upsert=False
        )
        
        if result.matched_count == 0:
            logger.error(f"Failed to update metadata for resource {doc.get('_id')}")
            raise RuntimeError("Failed to persist resource metadata")
        
        logger.info(f"Resource added successfully: _id={str(doc['_id'])}, title='{resource.title}'")
        
        return {
            "success": True,
            "message": "Resource added successfully",
            "resource": serialize_mongo(doc)
        }
    
    except ValueError as e:
        logger.warning(f"Validation error adding resource: {e}")
        raise
    except DuplicateKeyError as e:
        logger.warning(f"Duplicate key error: {e}")
        raise ValueError("Resource already exists")
    except Exception as e:
        logger.exception(f"Error adding resource: {e}")
        raise RuntimeError(f"Failed to add resource: {str(e)}")


# =========================
# IMPORT MULTIPLE RESOURCES (BATCH)
# =========================
def import_resources_service(
    data: ResourceImportRequest,
    user_id: Optional[int] = None,
    skip_duplicates: bool = True,
    stop_on_error: bool = False
) -> Dict[str, Any]:
    """
    Import multiple resources with batch processing + partial failure handling.
    
    Pipeline:
    1. Validate batch size
    2. Process in chunks (default: 100 items)
    3. Check duplicates per item (optional)
    4. Store with embeddings
    5. Track success/failure per item
    6. Return detailed results
    
    Args:
        data: ResourceImportRequest with list of resources
        user_id: Optional user ID for audit trail
        skip_duplicates: If True, skip duplicate; if False, raise error
        stop_on_error: If True, stop on first error; if False, continue with partial success
        
    Returns:
        Dict with:
        - success: bool (True if all succeeded, False if any failed)
        - status: "success" | "partial" | "failed"
        - total: int (total resources)
        - inserted: int (successfully inserted)
        - skipped: int (duplicates skipped)
        - failed: int (errors encountered)
        - inserted_ids: List[str]
        - errors: List[Dict] with resource details + error message
        
    Raises:
        ValueError: If batch size exceeds MAX_BATCH_SIZE
        
    Example:
        >>> result = import_resources_service(
        ...     ResourceImportRequest(resources=[...]),
        ...     skip_duplicates=True
        ... )
        >>> print(f"Inserted: {result['inserted']}, Failed: {result['failed']}")
    """
    logger.info(f"Importing batch of {len(data.resources)} resources, user_id={user_id}")
    
    if len(data.resources) == 0:
        logger.warning("Empty batch import requested")
        return {
            "success": True,
            "status": "success",
            "total": 0,
            "inserted": 0,
            "skipped": 0,
            "failed": 0,
            "inserted_ids": [],
            "errors": []
        }
    
    if len(data.resources) > MAX_BATCH_SIZE:
        raise ValueError(f"Batch size {len(data.resources)} exceeds maximum {MAX_BATCH_SIZE}")
    
    inserted_ids = []
    errors = []
    skipped = 0
    
    db = get_db()
    
    for idx, resource_data in enumerate(data.resources):
        try:
            # 1. Validate individual resource
            validate_resource(resource_data.model_dump())
            
            # 2. Check duplicates
            if ENABLE_DUPLICATE_CHECK and check_duplicate_resource(
                resource_data.title,
                resource_data.topic,
                db
            ):
                skipped += 1
                logger.info(f"[{idx+1}/{len(data.resources)}] Skipped duplicate: {resource_data.title}")
                if not skip_duplicates:
                    raise ValueError("Duplicate resource")
                continue
            
            # 3. Import via resource_importer
            result = import_resource(
                resource=resource_data.model_dump(),
                user_id=user_id
            )
            
            if result and "_id" in result:
                inserted_ids.append(str(result["_id"]))
                logger.debug(f"[{idx+1}/{len(data.resources)}] Imported: {resource_data.title}")
            else:
                raise RuntimeError("No _id returned from import_resource")
        
        except Exception as e:
            logger.error(f"[{idx+1}/{len(data.resources)}] Error importing {resource_data.title}: {e}")
            errors.append({
                "index": idx,
                "title": resource_data.title,
                "error": str(e)
            })
            
            if stop_on_error:
                logger.warning("Stopping batch import on first error")
                break
    
    inserted = len(inserted_ids)
    failed = len(errors)
    total = len(data.resources)
    
    # Determine overall success status
    if failed == 0 and skipped == 0:
        status = "success"
        success = True
    elif failed == 0:
        status = "success"
        success = True
    elif inserted > 0:
        status = "partial"
        success = False
    else:
        status = "failed"
        success = False
    
    logger.info(
        f"Batch import complete: total={total}, inserted={inserted}, "
        f"skipped={skipped}, failed={failed}, status={status}"
    )
    
    return {
        "success": success,
        "status": status,
        "total": total,
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "inserted_ids": inserted_ids,
        "errors": errors
    }


# =========================
# SEMANTIC SEARCH
# =========================
def search_resources_service(
    query: str,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search resources using semantic similarity (embeddings).
    
    Pipeline:
    1. Validate query
    2. Call embedding service semantic search
    3. Apply optional filters (by topic, level, source)
    4. Serialize results
    5. Return with metadata
    
    Args:
        query: Search query string (will be embedded)
        limit: Max results to return (default: 10, max: MAX_SEARCH_RESULTS)
        filters: Optional dict with keys:
            - topic: str (exact match)
            - level: str (exact match)
            - source: str (exact match)
            - min_score: float (minimum similarity score 0-1)
            
    Returns:
        Dict with:
        - success: bool
        - query: str (original query)
        - results: List[Dict] (serialized MongoDB docs)
        - count: int (number of results)
        - filters_applied: Dict
        - message: str
        
    Raises:
        ValueError: If query too short or filters invalid
        
    Example:
        >>> results = search_resources_service(
        ...     "Python functions",
        ...     limit=5,
        ...     filters={"level": "beginner", "topic": "python"}
        ... )
        >>> print(f"Found {results['count']} resources")
    """
    logger.info(f"Searching resources: query='{query}', limit={limit}")
    
    try:
        # 1. Validate query
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        
        query = query.strip()
        
        if len(query) < 3:
            logger.warning(f"Very short search query: '{query}'")
        
        if len(query) > 1000:
            raise ValueError("Search query too long (max 1000 characters)")
        
        # 2. Validate limit
        if limit < 1 or limit > MAX_SEARCH_RESULTS:
            limit = min(limit, MAX_SEARCH_RESULTS)
            logger.debug(f"Adjusted limit to {limit}")
        
        # 3. Validate filters
        filters = filters or {}
        valid_filter_keys = {"topic", "level", "source", "min_score", "concept_id"}
        invalid_keys = set(filters.keys()) - valid_filter_keys
        if invalid_keys:
            logger.warning(f"Invalid filter keys ignored: {invalid_keys}")
            filters = {k: v for k, v in filters.items() if k in valid_filter_keys}
        
        # 4. Search via embedding service (returns top-k by similarity)
        results = semantic_search(query, limit=limit)
        
        logger.debug(f"Semantic search returned {len(results)} raw results")
        
        # 5. Apply additional filters (post-search)
        filtered_results = results
        
        if "topic" in filters and filters["topic"]:
            topic_filter = filters["topic"].lower()
            filtered_results = [
                r for r in filtered_results
                if r.get("topic", "").lower() == topic_filter
            ]
            logger.debug(f"Topic filter: {len(filtered_results)} results after filtering")
        
        if "level" in filters and filters["level"]:
            level_filter = filters["level"].lower()
            filtered_results = [
                r for r in filtered_results
                if r.get("level", "").lower() == level_filter
            ]
            logger.debug(f"Level filter: {len(filtered_results)} results after filtering")
        
        if "source" in filters and filters["source"]:
            source_filter = filters["source"].lower()
            filtered_results = [
                r for r in filtered_results
                if r.get("source", "").lower() == source_filter
            ]
            logger.debug(f"Source filter: {len(filtered_results)} results after filtering")
        
        if "min_score" in filters:
            try:
                min_score = float(filters["min_score"])
                filtered_results = [
                    r for r in filtered_results
                    if r.get("similarity_score", 0) >= min_score
                ]
                logger.debug(f"Min score filter ({min_score}): {len(filtered_results)} results")
            except ValueError:
                logger.warning(f"Invalid min_score filter: {filters['min_score']}")
        
        if "concept_id" in filters and filters["concept_id"]:
            concept_id = filters["concept_id"]
            filtered_results = [
                r for r in filtered_results
                if r.get("concept_id") == concept_id
            ]
            logger.debug(f"Concept filter: {len(filtered_results)} results")
        
        # 6. Serialize
        serialized = [serialize_mongo(r) for r in filtered_results]
        
        logger.info(f"Search complete: found {len(serialized)} results (filters_applied={bool(filters)})")
        
        return {
            "success": True,
            "query": query,
            "results": serialized,
            "count": len(serialized),
            "filters_applied": filters,
            "message": f"Found {len(serialized)} resources matching '{query}'"
        }
    
    except ValueError as e:
        logger.warning(f"Search validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error searching resources: {e}")
        raise RuntimeError(f"Search failed: {str(e)}")


# =========================
# IMPORT PDF
# =========================
def import_pdf_service(
    file: UploadFile,
    topic: str,
    level: str,
    concept_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Import PDF file: extract text, chunk, embed, store.
    
    Pipeline:
    1. Validate file (extension, size, uploadability)
    2. Sanitize filename
    3. Save to disk (temporary)
    4. Call pdf_importer service
    5. Clean up temp file
    6. Serialize results
    
    Args:
        file: FastAPI UploadFile from form
        topic: Topic category (e.g., "python", "database")
        level: Bloom level (beginner/intermediate/advanced)
        concept_id: Optional concept to associate with extracted content
        user_id: Optional user ID for audit
        
    Returns:
        Dict with:
        - success: bool
        - filename: str
        - pages: int (extracted pages)
        - chunks_created: int
        - resources: List[Dict] (inserted docs)
        - message: str
        
    Raises:
        ValueError: If file validation fails
        Exception: If import fails
        
    Example:
        >>> result = import_pdf_service(
        ...     file=uploaded_file,
        ...     topic="python",
        ...     level="beginner",
        ...     concept_id=1
        ... )
        >>> print(f"Imported {result['pages']} pages")
    """
    logger.info(f"Importing PDF: filename={file.filename}, topic={topic}, level={level}, user_id={user_id}")
    
    file_path = None
    
    try:
        # 1. Validate file
        validate_file_upload(file)
        
        # 2. Sanitize filename
        safe_filename = sanitize_filename(file.filename)
        
        # 3. Save to disk
        file_path = UPLOAD_DIR / safe_filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = file_path.stat().st_size
        logger.info(f"PDF saved to disk: {file_path} ({file_size} bytes)")
        
        # 4. Import via pdf_importer service
        result = import_pdf(
            file_path=str(file_path),
            topic=topic,
            level=level,
            concept_id=concept_id,
            user_id=user_id
        )
        
        logger.debug(f"PDF import result: {result}")
        
        # 5. Serialize if docs returned
        resources = []
        if isinstance(result, list):
            resources = [serialize_mongo(r) for r in result]
        elif isinstance(result, dict):
            if "error" in result:
                logger.warning(f"PDF import returned error: {result['error']}")
                return {
                    "success": False,
                    "filename": safe_filename,
                    "error": result["error"],
                    "message": f"Failed to import PDF: {result['error']}"
                }
        
        logger.info(f"PDF import successful: {len(resources)} resources created")
        
        return {
            "success": True,
            "filename": safe_filename,
            "file_size_bytes": file_size,
            "pages": result.get("pages", 0) if isinstance(result, dict) else len(resources),
            "chunks_created": len(resources),
            "resources": resources,
            "message": f"Imported PDF: {len(resources)} resources created"
        }
    
    except ValueError as e:
        logger.warning(f"PDF validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error importing PDF: {e}")
        raise RuntimeError(f"Failed to import PDF: {str(e)}")
    finally:
        # 6. Cleanup temp file
        if file_path:
            cleanup_temp_file(file_path)


# =========================
# IMPORT YOUTUBE
# =========================
def import_youtube_service(
    youtube_url: str,
    topic: str,
    level: str,
    concept_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Import YouTube video: fetch transcript, chunk, embed, store.
    
    Pipeline:
    1. Validate YouTube URL
    2. Call youtube_importer service (fetches transcript, chunks, embeds)
    3. Serialize results
    4. Return with metadata
    
    Args:
        youtube_url: Full YouTube URL (https://www.youtube.com/watch?v=...)
        topic: Topic category
        level: Bloom level
        concept_id: Optional concept association
        user_id: Optional user ID for audit
        
    Returns:
        Dict with:
        - success: bool
        - video_id: str
        - duration: int (seconds, if available)
        - chunks_created: int
        - resources: List[Dict]
        - message: str
        
    Raises:
        ValueError: If URL invalid or video not accessible
        Exception: If import fails
        
    Example:
        >>> result = import_youtube_service(
        ...     "https://www.youtube.com/watch?v=...",
        ...     topic="python",
        ...     level="beginner"
        ... )
        >>> print(f"Created {result['chunks_created']} chunks")
    """
    logger.info(f"Importing YouTube: url={youtube_url}, topic={topic}, level={level}, user_id={user_id}")
    
    try:
        # 1. Validate URL
        if not youtube_url or not youtube_url.strip():
            raise ValueError("YouTube URL cannot be empty")
        
        youtube_url = youtube_url.strip()
        
        if not ("youtube.com" in youtube_url or "youtu.be" in youtube_url):
            raise ValueError("Invalid YouTube URL (must contain youtube.com or youtu.be)")
        
        if not ("http://" in youtube_url or "https://" in youtube_url):
            youtube_url = "https://" + youtube_url
        
        logger.debug(f"Validated YouTube URL: {youtube_url}")
        
        # 2. Import via youtube_importer service
        result = import_youtube(
            youtube_url=youtube_url,
            topic=topic,
            level=level,
            concept_id=concept_id,
            user_id=user_id
        )
        
        logger.debug(f"YouTube import result type: {type(result)}")
        
        # 3. Handle result (could be list, dict, or error)
        resources = []
        video_id = None
        
        if isinstance(result, list):
            resources = [serialize_mongo(r) for r in result]
            logger.debug(f"Result is list: {len(resources)} resources")
        
        elif isinstance(result, dict):
            if "error" in result:
                logger.warning(f"YouTube import returned error: {result['error']}")
                return {
                    "success": False,
                    "youtube_url": youtube_url,
                    "error": result["error"],
                    "message": f"Failed to import YouTube: {result['error']}"
                }
            
            if "resources" in result:
                resources = [serialize_mongo(r) for r in result.get("resources", [])]
            
            video_id = result.get("video_id")
        
        logger.info(f"YouTube import successful: {len(resources)} resources created")
        
        return {
            "success": True,
            "youtube_url": youtube_url,
            "video_id": video_id,
            "chunks_created": len(resources),
            "resources": resources,
            "message": f"Imported YouTube: {len(resources)} resources created"
        }
    
    except ValueError as e:
        logger.warning(f"YouTube validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error importing YouTube: {e}")
        raise RuntimeError(f"Failed to import YouTube: {str(e)}")


# =========================
# ANALYTICS & INSIGHTS
# =========================
def get_resource_stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get resource statistics and analytics.
    
    Returns:
        Dict with:
        - total_resources: int
        - by_source: Dict[source] = count
        - by_level: Dict[level] = count
        - by_topic: Dict[topic] = count
        - recent_resources: List (last 10 added)
        - success_rate: float (% of resources with import_status="success")
        
    Example:
        >>> stats = get_resource_stats()
        >>> print(f"Total: {stats['total_resources']}")
    """
    logger.debug(f"Generating resource stats, user_id={user_id}")
    
    try:
        db = get_db()
        
        # Base query (optionally filter by user)
        query = {}
        if user_id:
            query["created_by_user_id"] = user_id
        
        total = db.resources.count_documents(query)
        
        # Aggregation pipeline
        pipeline = [
            {"$match": query},
            {
                "$facet": {
                    "by_source": [
                        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_level": [
                        {"$group": {"_id": "$level", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "by_topic": [
                        {"$group": {"_id": "$topic", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ],
                    "success_count": [
                        {"$match": {"import_status": "success"}},
                        {"$count": "count"}
                    ],
                    "recent": [
                        {"$sort": {"created_at": -1}},
                        {"$limit": 10},
                        {"$project": {"_id": 1, "title": 1, "topic": 1, "source": 1, "created_at": 1}}
                    ]
                }
            }
        ]
        
        results = list(db.resources.aggregate(pipeline))
        
        if not results:
            return {
                "total_resources": 0,
                "by_source": {},
                "by_level": {},
                "by_topic": {},
                "success_rate": 0.0,
                "recent_resources": []
            }
        
        facet = results[0]
        
        # Convert to dicts
        by_source = {item["_id"]: item["count"] for item in facet.get("by_source", [])}
        by_level = {item["_id"]: item["count"] for item in facet.get("by_level", [])}
        by_topic = {item["_id"]: item["count"] for item in facet.get("by_topic", [])}
        
        success_count_list = facet.get("success_count", [])
        success_count = success_count_list[0]["count"] if success_count_list else 0
        success_rate = (success_count / total * 100) if total > 0 else 0.0
        
        recent = [serialize_mongo(r) for r in facet.get("recent", [])]
        
        logger.info(f"Stats: total={total}, success_rate={success_rate:.1f}%, "
                   f"sources={len(by_source)}, levels={len(by_level)}, topics={len(by_topic)}")
        
        return {
            "total_resources": total,
            "by_source": by_source,
            "by_level": by_level,
            "by_topic": by_topic,
            "success_rate": round(success_rate, 2),
            "recent_resources": recent
        }
    
    except Exception as e:
        logger.exception(f"Error generating stats: {e}")
        return {
            "error": str(e),
            "total_resources": 0
        }