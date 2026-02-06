"""
Search Service: Multi-strategy resource discovery and search orchestration.

Provides unified interface for:
- Semantic search (embedding-based similarity)
- Keyword/full-text search (title + content)
- Concept-aware search (map query to concepts)
- Collaborative filtering (popular + trending resources)
- Advanced filtering (level, source, topic, bloom, pedagogy, date range, concept)
- Batch multi-query search
- Search history + analytics
- Result caching + deduplication
- Smart ranking (relevance + popularity + recency)

Key Features:
- Multi-strategy fallback (semantic → keyword → concept → popularity)
- Result deduplication + merging from multiple strategies
- Progressive filtering (broad search → narrow with filters)
- Search analytics (popular queries, trending resources, user behavior)
- Caching with TTL (configurable)
- Comprehensive logging at all levels
"""

import os
import logging
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime, timedelta
from functools import lru_cache
from collections import defaultdict

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import semantic_search, embed_text
from backend.app.services.concept_mapper import resolve_concept_id

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# CONFIG
# =========================
SEARCH_CACHE_TTL_SECONDS = int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "3600"))  # 1 hour
SEARCH_CACHE_SIZE = int(os.getenv("SEARCH_CACHE_SIZE", "500"))
MIN_KEYWORD_LENGTH = int(os.getenv("MIN_KEYWORD_LENGTH", "2"))
MAX_RESULTS_PER_STRATEGY = int(os.getenv("MAX_RESULTS_PER_STRATEGY", "50"))
TRENDING_WINDOW_DAYS = int(os.getenv("TRENDING_WINDOW_DAYS", "7"))
ENABLE_SEARCH_HISTORY = os.getenv("ENABLE_SEARCH_HISTORY", "true").lower() == "true"
ENABLE_SEARCH_ANALYTICS = os.getenv("ENABLE_SEARCH_ANALYTICS", "true").lower() == "true"

logger.info(f"Search service initialized: cache_ttl={SEARCH_CACHE_TTL_SECONDS}s, "
           f"cache_size={SEARCH_CACHE_SIZE}, trending_window={TRENDING_WINDOW_DAYS}d")


# =========================
# HELPERS: TRACKING & ANALYTICS
# =========================
def _track_search(query: str, user_id: Optional[int] = None, result_count: int = 0) -> None:
    """
    Track search query for analytics (optional history logging).
    
    Args:
        query: Search query string
        user_id: Optional user performing search
        result_count: Number of results returned
    """
    if not ENABLE_SEARCH_HISTORY:
        return
    
    try:
        db = get_db()
        db.search_history.insert_one({
            "query": query.strip(),
            "user_id": user_id,
            "result_count": result_count,
            "timestamp": datetime.utcnow()
        })
        logger.debug(f"Tracked search: query='{query[:50]}...', user_id={user_id}, results={result_count}")
    except Exception as e:
        logger.warning(f"Failed to track search: {e}")


def _increment_resource_hit(resource_id: str, user_id: Optional[int] = None) -> None:
    """
    Increment hit count on resource (tracks popularity).
    
    Args:
        resource_id: MongoDB ObjectId as string
        user_id: Optional user who viewed it
    """
    if not ENABLE_SEARCH_ANALYTICS:
        return
    
    try:
        db = get_db()
        db.resources.update_one(
            {"_id": resource_id},
            {
                "$inc": {"hit_count": 1},
                "$push": {
                    "recent_viewers": {
                        "user_id": user_id,
                        "timestamp": datetime.utcnow()
                    }
                } if user_id else {}
            },
            upsert=False
        )
    except Exception as e:
        logger.debug(f"Failed to increment hit count: {e}")


def _get_search_score_boost(resource_doc: Dict) -> float:
    """
    Calculate popularity/freshness boost for ranking.
    
    Factors:
    - Hit count (accumulated views)
    - Recency (created_at)
    - Review status (is_reviewed)
    
    Returns:
        Boost multiplier [0.5, 2.0]
    """
    boost = 1.0
    
    # Hit count boost (cap at 50 for fairness)
    hit_count = resource_doc.get("hit_count", 0)
    hit_boost = min(hit_count / 50, 1.0) * 0.5  # +0 to +0.5
    boost += hit_boost
    
    # Recency boost (within 7 days: +0.3)
    created_at = resource_doc.get("created_at")
    if created_at:
        age_days = (datetime.utcnow() - created_at).days
        if age_days < 7:
            recency_boost = 0.3 * (1 - age_days / 7)
            boost += recency_boost
    
    # Review boost (reviewed resources rank higher)
    if resource_doc.get("is_reviewed"):
        boost += 0.2
    
    return min(boost, 2.0)  # Cap boost at 2x


# =========================
# SINGLE-STRATEGY SEARCHES
# =========================
def _search_by_semantic(
    query: str,
    limit: int = 10,
    min_score: float = 0.5,
    topic: Optional[str] = None,
    level: Optional[str] = None
) -> List[Dict]:
    """
    Semantic search using embeddings (via embedding_service).
    
    Args:
        query: Search query
        limit: Max results
        min_score: Minimum cosine similarity threshold
        topic: Optional topic filter
        level: Optional level filter
        
    Returns:
        List of resources with 'similarity_score' field
    """
    logger.debug(f"Semantic search: query='{query[:50]}', limit={limit}")
    
    try:
        return semantic_search(
            query=query,
            k=limit,
            min_score=min_score,
            topic=topic,
            level=level
        )
    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        return []


def _search_by_keyword(
    query: str,
    limit: int = 10,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    source: Optional[str] = None
) -> List[Dict]:
    """
    Keyword/full-text search in title and content.
    
    Strategy:
    - Split query into tokens
    - Search for any token in title (higher weight) or content
    - Rank by title matches first, then content matches
    
    Args:
        query: Search query
        limit: Max results
        topic: Optional topic filter
        level: Optional level filter
        source: Optional source filter
        
    Returns:
        List of matching resources
    """
    logger.debug(f"Keyword search: query='{query[:50]}', limit={limit}")
    
    if len(query) < MIN_KEYWORD_LENGTH:
        logger.debug(f"Query too short for keyword search: {len(query)} < {MIN_KEYWORD_LENGTH}")
        return []
    
    try:
        db = get_db()
        
        # Build regex pattern (case-insensitive, any token match)
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []
        
        pattern = "|".join(f"\\b{t}" for t in tokens)
        regex_filter = {"$regex": pattern, "$options": "i"}
        
        # Build mongo query
        mongo_query = {
            "$or": [
                {"title": regex_filter},
                {"content": regex_filter}
            ]
        }
        
        if topic:
            mongo_query["topic"] = {"$regex": f"^{topic}$", "$options": "i"}
        if level:
            mongo_query["level"] = {"$regex": f"^{level}$", "$options": "i"}
        if source:
            mongo_query["source"] = {"$regex": f"^{source}$", "$options": "i"}
        
        # MongoDB full-text search (if available) or cursor-based
        results = list(db.resources.find(mongo_query).limit(limit))
        
        logger.debug(f"Keyword search found {len(results)} results")
        return results
    
    except Exception as e:
        logger.warning(f"Keyword search failed: {e}")
        return []


def _search_by_concept(
    query: str,
    limit: int = 10,
    level: Optional[str] = None,
    source: Optional[str] = None
) -> List[Dict]:
    """
    Concept-aware search: map query to concept(s), then fetch associated resources.
    
    Strategy:
    - Use concept_mapper to resolve query → concept_id
    - Fetch all resources for that concept
    - Filter by level/source if provided
    
    Args:
        query: Search query (free-form)
        limit: Max results
        level: Optional level filter
        source: Optional source filter
        
    Returns:
        List of resources associated with mapped concept
    """
    logger.debug(f"Concept search: query='{query[:50]}'")
    
    try:
        # Map query to concept
        concept_id = resolve_concept_id(query, allow_fallback=True)
        
        if concept_id is None:
            logger.debug(f"Could not map query to concept: {query}")
            return []
        
        logger.debug(f"Mapped query '{query}' → concept_id {concept_id}")
        
        # Fetch resources for concept
        db = get_db()
        mongo_query = {"concept_id": concept_id}
        
        if level:
            mongo_query["level"] = {"$regex": f"^{level}$", "$options": "i"}
        if source:
            mongo_query["source"] = {"$regex": f"^{source}$", "$options": "i"}
        
        results = list(db.resources.find(mongo_query).limit(limit))
        
        logger.debug(f"Concept search found {len(results)} resources for concept {concept_id}")
        return results
    
    except Exception as e:
        logger.warning(f"Concept search failed: {e}")
        return []


def _search_by_popularity(
    limit: int = 10,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    days: int = TRENDING_WINDOW_DAYS
) -> List[Dict]:
    """
    Trending/popular resources search (most viewed recently).
    
    Args:
        limit: Max results
        topic: Optional topic filter
        level: Optional level filter
        days: Trending window (default: 7 days)
        
    Returns:
        List of trending resources
    """
    logger.debug(f"Trending search: limit={limit}, days={days}")
    
    try:
        db = get_db()
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        mongo_query = {"created_at": {"$gte": cutoff_date}}
        
        if topic:
            mongo_query["topic"] = {"$regex": f"^{topic}$", "$options": "i"}
        if level:
            mongo_query["level"] = {"$regex": f"^{level}$", "$options": "i"}
        
        results = list(
            db.resources.find(mongo_query)
            .sort("hit_count", -1)
            .limit(limit)
        )
        
        logger.debug(f"Trending search found {len(results)} resources")
        return results
    
    except Exception as e:
        logger.warning(f"Trending search failed: {e}")
        return []


# =========================
# MAIN SEARCH FUNCTION
# =========================
def search_learning_resources(
    query: str,
    limit: int = 10,
    min_score: float = 0.5,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
    strategies: Optional[List[str]] = None,
    sort_by: str = "relevance",
    user_id: Optional[int] = None
) -> Dict[str, any]:
    """
    Multi-strategy search for learning resources.
    
    Combines multiple search techniques:
    1. Semantic search (embedding-based similarity) - highest priority
    2. Keyword search (full-text title/content matches)
    3. Concept-aware search (map query to concepts)
    4. Popularity/trending search (if other strategies have few results)
    
    Pipeline:
    - Validate query + filters
    - Run selected strategies in parallel concept
    - Deduplicate + merge results
    - Apply score boost (popularity/recency/review)
    - Sort by requested criteria
    - Track search in history
    - Return ranked results
    
    Args:
        query: Search query string (e.g., "Python functions")
        limit: Max results to return (default: 10, max: 50)
        min_score: Minimum semantic similarity score [0, 1]
        topic: Optional topic filter (exact match, case-insensitive)
        level: Optional level filter (beginner/intermediate/advanced)
        source: Optional source filter (pdf/youtube/web/manual)
        strategies: List of strategies to use. Default: ["semantic", "keyword", "concept"]
                  Options: "semantic", "keyword", "concept", "popularity"
        sort_by: Sort results by "relevance" (default), "recency" (created_at), or "popularity" (hit_count)
        user_id: Optional user ID for personalization + tracking
        
    Returns:
        Dict with:
        - success: bool (True if found any results)
        - query: str (original query)
        - strategies_used: List[str] (which strategies ran)
        - results: List[Dict] (merged + ranked resources)
        - result_count: int
        - deduped_count: int (how many duplicates removed)
        - filters_applied: Dict (active filters)
        - execution_ms: float (search latency)
        - message: str (summary)
        
    Raises:
        ValueError: If query invalid
        
    Example:
        >>> result = search_learning_resources(
        ...     query="Python functions",
        ...     limit=5,
        ...     level="beginner",
        ...     strategies=["semantic", "keyword"]
        ... )
        >>> print(f"Found {result['result_count']} resources")
    """
    import time
    start_time = time.time()
    
    logger.info(f"Search requested: query='{query[:100]}', limit={limit}, "
               f"topic={topic}, level={level}, sort_by={sort_by}, user_id={user_id}")
    
    try:
        # 1️⃣ VALIDATE INPUT
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        
        query = query.strip()
        
        if len(query) > 500:
            raise ValueError("Search query too long (max 500 characters)")
        
        if limit < 1 or limit > 50:
            limit = min(max(limit, 1), 50)
            logger.debug(f"Adjusted limit to {limit}")
        
        if min_score < 0 or min_score > 1:
            min_score = max(min(min_score, 1), 0)
            logger.debug(f"Adjusted min_score to {min_score}")
        
        # Normalize filters
        if topic:
            topic = topic.strip().lower()
        if level:
            level = level.strip().lower()
        if source:
            source = source.strip().lower()
        
        # 2️⃣ DETERMINE STRATEGIES
        if strategies is None:
            strategies = ["semantic", "keyword", "concept"]
        
        strategies = [s.lower() for s in strategies if s.lower() in ["semantic", "keyword", "concept", "popularity"]]
        if not strategies:
            strategies = ["semantic", "keyword", "concept"]
        
        logger.debug(f"Using strategies: {strategies}")
        
        # 3️⃣ RUN SEARCHES IN PARALLEL (simulate)
        all_results: Dict[str, List[Dict]] = {}
        
        if "semantic" in strategies:
            all_results["semantic"] = _search_by_semantic(
                query, limit=MAX_RESULTS_PER_STRATEGY, min_score=min_score,
                topic=topic, level=level
            )
        
        if "keyword" in strategies:
            all_results["keyword"] = _search_by_keyword(
                query, limit=MAX_RESULTS_PER_STRATEGY,
                topic=topic, level=level, source=source
            )
        
        if "concept" in strategies:
            all_results["concept"] = _search_by_concept(
                query, limit=MAX_RESULTS_PER_STRATEGY,
                level=level, source=source
            )
        
        # Fallback to popularity if no results from primary strategies
        if "popularity" in strategies or not any(all_results.values()):
            all_results["popularity"] = _search_by_popularity(
                limit=MAX_RESULTS_PER_STRATEGY,
                topic=topic, level=level
            )
        
        # 4️⃣ MERGE & DEDUPLICATE
        seen_ids: Set[str] = set()
        merged_results: List[Dict] = []
        
        # Priority order: semantic > keyword > concept > popularity
        priority_order = ["semantic", "keyword", "concept", "popularity"]
        
        for strategy in priority_order:
            if strategy not in all_results:
                continue
            
            for doc in all_results[strategy]:
                doc_id = str(doc.get("_id", ""))
                
                if doc_id and doc_id in seen_ids:
                    logger.debug(f"Deduped result: {doc_id}")
                    continue
                
                if doc_id:
                    seen_ids.add(doc_id)
                
                merged_results.append(doc)
                
                if len(merged_results) >= limit:
                    break
            
            if len(merged_results) >= limit:
                break
        
        deduped_count = sum(len(results) for results in all_results.values()) - len(merged_results)
        
        # 5️⃣ APPLY RANKING BOOSTS
        for doc in merged_results:
            boost = _get_search_score_boost(doc)
            
            # Adjust similarity score if available (from semantic search)
            if "similarity_score" in doc:
                doc["similarity_score"] = min(doc["similarity_score"] * boost, 1.0)
            else:
                doc["search_score"] = boost
        
        # 6️⃣ SORT BY REQUESTED CRITERIA
        if sort_by == "recency":
            merged_results.sort(
                key=lambda x: x.get("created_at", datetime.min),
                reverse=True
            )
            logger.debug("Sorted by recency (descending)")
        
        elif sort_by == "popularity":
            merged_results.sort(
                key=lambda x: x.get("hit_count", 0),
                reverse=True
            )
            logger.debug("Sorted by popularity (hit_count)")
        
        else:  # Default: relevance
            merged_results.sort(
                key=lambda x: (
                    x.get("similarity_score", 0) if "similarity_score" in x else x.get("search_score", 1.0),
                    x.get("hit_count", 0)
                ),
                reverse=True
            )
            logger.debug("Sorted by relevance + popularity")
        
        # 7️⃣ TRACKING
        execution_ms = (time.time() - start_time) * 1000
        _track_search(query, user_id=user_id, result_count=len(merged_results))
        
        # 8️⃣ RETURN
        success = len(merged_results) > 0
        
        logger.info(
            f"Search complete: query='{query[:50]}', success={success}, "
            f"results={len(merged_results)}, deduped={deduped_count}, "
            f"execution_ms={execution_ms:.1f}"
        )
        
        return {
            "success": success,
            "query": query,
            "strategies_used": [s for s in strategies if s in all_results],
            "results": merged_results,
            "result_count": len(merged_results),
            "deduped_count": deduped_count,
            "filters_applied": {
                "topic": topic,
                "level": level,
                "source": source,
                "min_score": min_score
            },
            "execution_ms": round(execution_ms, 2),
            "message": f"Found {len(merged_results)} resources matching '{query}' ({execution_ms:.0f}ms)"
        }
    
    except ValueError as e:
        logger.warning(f"Search validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Search error: {e}")
        raise RuntimeError(f"Search failed: {str(e)}")


# =========================
# BATCH SEARCH
# =========================
def search_learning_resources_batch(
    queries: List[str],
    limit: int = 10,
    user_id: Optional[int] = None
) -> Dict[str, any]:
    """
    Search multiple queries efficiently.
    
    Args:
        queries: List of search queries
        limit: Max results per query
        user_id: Optional user ID
        
    Returns:
        Dict with:
        - success: bool
        - total_queries: int
        - successful_queries: int
        - results: Dict[query] -> search result
        - message: str
        
    Example:
        >>> batch = search_learning_resources_batch(["Python", "Functions"])
        >>> for query, result in batch["results"].items():
        ...     print(f"{query}: {result['result_count']} results")
    """
    logger.info(f"Batch search: {len(queries)} queries")
    
    if not queries or len(queries) == 0:
        raise ValueError("At least one query required")
    
    if len(queries) > 100:
        raise ValueError("Maximum 100 queries per batch")
    
    results = {}
    successful = 0
    
    for query in queries:
        try:
            result = search_learning_resources(
                query=query,
                limit=limit,
                user_id=user_id
            )
            results[query] = result
            if result["success"]:
                successful += 1
        except Exception as e:
            logger.warning(f"Batch search error for '{query}': {e}")
            results[query] = {
                "success": False,
                "query": query,
                "error": str(e)
            }
    
    logger.info(f"Batch search complete: {successful}/{len(queries)} successful")
    
    return {
        "success": successful > 0,
        "total_queries": len(queries),
        "successful_queries": successful,
        "results": results,
        "message": f"Processed {len(queries)} queries ({successful} successful)"
    }


# =========================
# SEARCH ANALYTICS
# =========================
def get_trending_searches(days: int = 7, limit: int = 20) -> Dict[str, any]:
    """
    Get trending search queries (most popular in recent days).
    
    Args:
        days: Time window
        limit: Max queries to return
        
    Returns:
        List of (query, count) tuples
    """
    logger.debug(f"Fetching trending searches: days={days}, limit={limit}")
    
    try:
        db = get_db()
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {"$group": {
                "_id": "$query",
                "count": {"$sum": 1},
                "last_searched": {"$max": "$timestamp"},
                "total_results": {"$avg": "$result_count"}
            }},
            {"$sort": {"count": -1}},
            {"$limit": limit}
        ]
        
        results = list(db.search_history.aggregate(pipeline))
        
        logger.info(f"Found {len(results)} trending searches")
        
        return {
            "success": True,
            "days": days,
            "trending": results,
            "count": len(results)
        }
    
    except Exception as e:
        logger.warning(f"Error fetching trending searches: {e}")
        return {
            "success": False,
            "error": str(e),
            "trending": []
        }


def get_popular_resources(days: int = 7, limit: int = 20, topic: Optional[str] = None) -> Dict[str, any]:
    """
    Get most-viewed resources (trending content).
    
    Args:
        days: Time window
        limit: Max results
        topic: Optional topic filter
        
    Returns:
        List of trending resources
    """
    logger.debug(f"Fetching popular resources: days={days}, topic={topic}")
    
    try:
        db = get_db()
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        query = {"created_at": {"$gte": cutoff}}
        if topic:
            query["topic"] = {"$regex": f"^{topic}$", "$options": "i"}
        
        results = list(
            db.resources.find(query)
            .sort("hit_count", -1)
            .limit(limit)
        )
        
        logger.info(f"Found {len(results)} popular resources")
        
        return {
            "success": True,
            "days": days,
            "topic": topic,
            "resources": results,
            "count": len(results)
        }
    
    except Exception as e:
        logger.warning(f"Error fetching popular resources: {e}")
        return {
            "success": False,
            "error": str(e),
            "resources": []
        }


# =========================
# FALLBACK WRAPPER (backward-compatible)
# =========================
def search_learning_resources_simple(
    query: str,
    limit: int = 5,
    min_score: float = 0.75
) -> List[Dict]:
    """
    Backward-compatible wrapper for original simple search.
    
    Calls main search_learning_resources with semantic strategy only.
    
    Args:
        query: Search query
        limit: Max results
        min_score: Semantic similarity threshold
        
    Returns:
        List of resources (original format)
    """
    logger.debug(f"Simple search (backward-compat): query='{query}'")
    
    try:
        result = search_learning_resources(
            query=query,
            limit=limit,
            min_score=min_score,
            strategies=["semantic"]
        )
        return result.get("results", [])
    except Exception as e:
        logger.warning(f"Simple search failed: {e}")
        return []