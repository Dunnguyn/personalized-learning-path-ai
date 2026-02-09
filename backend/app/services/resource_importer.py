from typing import List, Dict, Optional
import logging
from datetime import datetime
from pymongo.errors import DuplicateKeyError, BulkWriteError

from backend.app.services.embedding_service import embed_text
from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)

# ==================================================
# CONFIG
# ==================================================
BATCH_SIZE = 100
MAX_TITLE_LEN = 500
MAX_CONTENT_LEN = 50000
MAX_TOPIC_LEN = 100
VALID_SOURCES = ("pdf", "youtube", "web", "manual")
VALID_LEVELS = ("beginner", "intermediate", "advanced")


# ==================================================
# VALIDATION & NORMALIZATION
# ==================================================
def _validate_resource(resource: Dict, idx: int) -> tuple[bool, Optional[str]]:
    """
    Validate a single resource.
    Returns (is_valid, error_message)
    """
    # Check required fields
    title = resource.get("title", "").strip()
    content = resource.get("content", "").strip()
    topic = resource.get("topic", "").strip()

    if not title:
        return False, f"Resource {idx}: title is required"
    if not content:
        return False, f"Resource {idx}: content is required"
    if not topic:
        return False, f"Resource {idx}: topic is required"

    # Check length constraints
    if len(title) > MAX_TITLE_LEN:
        return False, f"Resource {idx}: title too long (max {MAX_TITLE_LEN} chars)"
    if len(content) > MAX_CONTENT_LEN:
        return False, f"Resource {idx}: content too long (max {MAX_CONTENT_LEN} chars)"
    if len(topic) > MAX_TOPIC_LEN:
        return False, f"Resource {idx}: topic too long (max {MAX_TOPIC_LEN} chars)"

    # Check optional fields
    level = resource.get("level", "beginner").lower()
    if level not in VALID_LEVELS:
        return False, f"Resource {idx}: invalid level '{level}' (must be one of {VALID_LEVELS})"

    source = resource.get("source", "manual").lower()
    if source not in VALID_SOURCES:
        return False, f"Resource {idx}: invalid source '{source}' (must be one of {VALID_SOURCES})"

    url = resource.get("url")
    if url and len(url) > 2000:
        return False, f"Resource {idx}: URL too long"

    return True, None


def validate_resource(resource: Dict, idx: int = 0) -> None:
    """
    Validate a single resource.
    Raises ValueError if validation fails.
    """
    is_valid, error_message = _validate_resource(resource, idx)
    if not is_valid:
        raise ValueError(error_message)


def _normalize_resource(resource: Dict) -> Dict:
    """
    Normalize and enrich a resource document.
    """
    return {
        "title": resource.get("title", "").strip(),
        "content": resource.get("content", "").strip(),
        "topic": resource.get("topic", "").strip().lower(),
        "level": resource.get("level", "beginner").lower(),
        "source": resource.get("source", "manual").lower(),
        "url": resource.get("url") or None,
        "concept_id": resource.get("concept_id"),
        "pedagogy_type": resource.get("pedagogy_type"),
        "bloom_level": resource.get("bloom_level"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }


# ==================================================
# DUPLICATE DETECTION
# ==================================================
def _check_duplicate(db, title: str, topic: str, content_hash: Optional[str] = None) -> bool:
    """
    Check if resource already exists (by title + topic).
    """
    try:
        existing = db.resources.find_one(
            {"title": title, "topic": topic},
            {"_id": 1}
        )
        return existing is not None
    except Exception as e:
        logger.debug(f"Duplicate check error: {e}")
        return False


# ==================================================
# SINGLE RESOURCE IMPORT
# ==================================================
def import_resource(
    title: str,
    content: str,
    topic: str,
    level: str = "beginner",
    source: str = "manual",
    url: Optional[str] = None,
    concept_id: Optional[int] = None,
    pedagogy_type: Optional[str] = None,
    bloom_level: Optional[str] = None,
    skip_duplicates: bool = True
) -> Dict:
    """
    Import a single learning resource.
    
    Parameters
    ----------
    title, content, topic, level, source, url : as in batch import
    concept_id : associated concept ID
    pedagogy_type : "video" | "text" | "quiz"
    bloom_level : "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create"
    skip_duplicates : if True, don't insert if duplicate found
    
    Returns
    -------
    Dict : {"success": bool, "resource_id": str, "message": str}
    """
    db = get_db()
    
    resource = {
        "title": title,
        "content": content,
        "topic": topic,
        "level": level,
        "source": source,
        "url": url,
        "concept_id": concept_id,
        "pedagogy_type": pedagogy_type,
        "bloom_level": bloom_level
    }
    
    # Validate
    is_valid, error = _validate_resource(resource, 0)
    if not is_valid:
        logger.warning(f"Validation failed: {error}")
        return {"success": False, "error": error}
    
    # Check duplicate
    if skip_duplicates and _check_duplicate(db, title, topic):
        logger.info(f"Skipping duplicate resource: {title}")
        return {"success": False, "error": "duplicate"}
    
    # Generate embedding
    try:
        embedding = embed_text(content)
    except Exception as e:
        logger.exception(f"Embedding error: {e}")
        return {"success": False, "error": f"embedding_failed: {str(e)}"}
    
    # Normalize and enrich
    doc = _normalize_resource(resource)
    doc["embedding"] = embedding
    
    # Insert into DB
    try:
        result = db.resources.insert_one(doc)
        resource_id = str(result.inserted_id)
        
        logger.info(f"Resource imported: {resource_id} - {title}")
        
        return {
            "success": True,
            "resource_id": resource_id,
            "title": title,
            "message": f"Successfully imported: {title}"
        }
    
    except DuplicateKeyError as e:
        if skip_duplicates:
            logger.info(f"Duplicate key for resource: {title}")
            return {"success": False, "error": "duplicate"}
        else:
            raise
    except Exception as e:
        logger.exception(f"Error inserting resource: {e}")
        return {"success": False, "error": f"insert_failed: {str(e)}"}


# ==================================================
# BATCH IMPORT
# ==================================================
def import_resources(
    resources: List[Dict],
    skip_duplicates: bool = True,
    stop_on_error: bool = False
) -> Dict:
    """
    Import batch of learning resources.
    
    Pipeline:
    1. Validate each resource
    2. Check duplicates (optional)
    3. Generate embeddings
    4. Batch insert into MongoDB
    
    Parameters
    ----------
    resources : List[Dict]
        List of resource objects, each with:
        - title (str, required)
        - content (str, required)
        - topic (str, required)
        - level (str, default="beginner")
        - source (str, default="manual")
        - url (str, optional)
        - concept_id (int, optional)
        - pedagogy_type (str, optional)
        - bloom_level (str, optional)
    
    skip_duplicates : bool
        If True, skip duplicate resources (by title + topic)
    
    stop_on_error : bool
        If True, stop processing on first error
    
    Returns
    -------
    Dict : {
        "status": "success" | "partial" | "failed",
        "total": int,
        "inserted": int,
        "skipped": int,
        "failed": int,
        "errors": [...],
        "inserted_ids": [...]
    }
    """
    
    if not resources:
        logger.warning("Empty resources list provided")
        return {
            "status": "failed",
            "total": 0,
            "inserted": 0,
            "skipped": 0,
            "failed": 0,
            "errors": ["No resources provided"],
            "inserted_ids": []
        }
    
    db = get_db()
    logger.info(f"Starting batch import: {len(resources)} resources, skip_dup={skip_duplicates}")
    
    inserted = 0
    skipped = 0
    failed = 0
    errors = []
    inserted_ids = []
    
    # Process in batches
    for batch_start in range(0, len(resources), BATCH_SIZE):
        batch = resources[batch_start:batch_start + BATCH_SIZE]
        docs_to_insert = []
        
        for idx, resource in enumerate(batch, start=batch_start):
            try:
                # 1. Validate
                is_valid, error_msg = _validate_resource(resource, idx)
                if not is_valid:
                    logger.warning(f"Validation error: {error_msg}")
                    skipped += 1
                    errors.append({"idx": idx, "error": error_msg})
                    if stop_on_error:
                        raise ValueError(error_msg)
                    continue
                
                # 2. Check duplicate
                title = resource.get("title", "").strip()
                topic = resource.get("topic", "").strip()
                
                if skip_duplicates and _check_duplicate(db, title, topic):
                    logger.debug(f"Skipping duplicate: {title}")
                    skipped += 1
                    continue
                
                # 3. Generate embedding
                content = resource.get("content", "").strip()
                try:
                    embedding = embed_text(content)
                except Exception as e:
                    logger.warning(f"Embedding error for resource {idx}: {e}")
                    failed += 1
                    errors.append({"idx": idx, "error": f"embedding_failed: {str(e)}"})
                    if stop_on_error:
                        raise
                    continue
                
                # 4. Normalize and prepare for insert
                doc = _normalize_resource(resource)
                doc["embedding"] = embedding
                docs_to_insert.append(doc)
            
            except Exception as e:
                logger.exception(f"Error processing resource {idx}: {e}")
                failed += 1
                errors.append({"idx": idx, "error": str(e)})
                if stop_on_error:
                    break
        
        # Insert batch
        if docs_to_insert:
            try:
                result = db.resources.insert_many(docs_to_insert, ordered=False)
                batch_inserted = len(result.inserted_ids)
                inserted += batch_inserted
                inserted_ids.extend(str(id) for id in result.inserted_ids)
                
                logger.info(f"Batch inserted: {batch_inserted} resources")
            
            except BulkWriteError as e:
                # Partial success in bulk write
                logger.warning(f"Partial insert: {e.details['nInserted']} inserted, {len(e.details['writeErrors'])} errors")
                inserted += e.details.get("nInserted", 0)
                for err in e.details.get("writeErrors", []):
                    errors.append({"idx": batch_start + err.get("index", 0), "error": str(err.get("errmsg"))})
                    failed += 1
            
            except Exception as e:
                logger.exception(f"Batch insert error: {e}")
                failed += len(docs_to_insert)
                errors.append({"batch": batch_start, "error": str(e)})
                if stop_on_error:
                    break
    
    # Determine overall status
    if failed > 0 and inserted == 0:
        status = "failed"
    elif failed > 0 or skipped > 0:
        status = "partial"
    else:
        status = "success"
    
    logger.info(
        f"Batch import complete: status={status}, "
        f"inserted={inserted}, skipped={skipped}, failed={failed}, total={len(resources)}"
    )
    
    return {
        "status": status,
        "total": len(resources),
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "inserted_ids": inserted_ids,
        "message": f"Imported {inserted}/{len(resources)} resources"
    }


# ==================================================
# OPTIMIZE & MAINTENANCE
# ==================================================
def create_resource_indexes(db) -> Dict:
    """
    Create recommended indexes for resource collection.
    (Called during app startup or manually)
    """
    try:
        indexes = [
            [("topic", 1)],
            [("level", 1)],
            [("source", 1)],
            [("topic", 1), ("level", 1)],
            [("created_at", -1)],
            [("title", 1), ("topic", 1)]  # For duplicate detection
        ]
        
        for index_spec in indexes:
            try:
                db.resources.create_index(index_spec)
            except Exception as e:
                logger.debug(f"Index creation skipped (may already exist): {e}")
        
        logger.info("Resource indexes created/verified")
        return {"success": True, "indexes_created": len(indexes)}
    
    except Exception as e:
        logger.exception(f"Error creating indexes: {e}")
        return {"success": False, "error": str(e)}


def delete_duplicate_resources(db) -> Dict:
    """
    Remove duplicate resources (same title + topic).
    Keeps the most recent one.
    """
    try:
        # Find duplicate groups
        pipeline = [
            {"$group": {
                "_id": {"title": "$title", "topic": "$topic"},
                "count": {"$sum": 1},
                "ids": {"$push": "$_id"},
                "latest": {"$max": "$created_at"}
            }},
            {"$match": {"count": {"$gt": 1}}}
        ]
        
        duplicates = list(db.resources.aggregate(pipeline))
        deleted = 0
        
        for dup in duplicates:
            ids = dup["ids"]
            # Keep the first (earliest inserted), delete rest
            to_delete = ids[1:]
            result = db.resources.delete_many({"_id": {"$in": to_delete}})
            deleted += result.deleted_count
        
        logger.info(f"Deleted {deleted} duplicate resources")
        return {"success": True, "deleted_count": deleted}
    
    except Exception as e:
        logger.exception(f"Error deleting duplicates: {e}")
        return {"success": False, "error": str(e)}