from typing import List, Dict, Optional
import logging
import numpy as np
from datetime import datetime, timedelta
from functools import lru_cache

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import embed_text, cosine_similarity

logger = logging.getLogger(__name__)

# ==================================================
# CONFIG
# ==================================================
MAX_RECOMMENDATIONS = 10
MIN_RESOURCES_FALLBACK = 3
RECENCY_BOOST_DAYS = 7
DEFAULT_SCORE = 0.5


# ==================================================
# VALIDATION
# ==================================================
def _validate_concept(db, concept_id: int) -> bool:
    """Check if concept exists in database."""
    try:
        concept = db.concepts.find_one(
            {"concept_id": concept_id},
            {"concept_id": 1}
        )
        return concept is not None
    except Exception as e:
        logger.debug(f"Concept validation error: {e}")
        return False


def _validate_level(level: str) -> bool:
    """Validate level enum."""
    valid_levels = ("beginner", "intermediate", "advanced")
    return level.lower() in valid_levels


# ==================================================
# SCORING & RANKING
# ==================================================
def _calculate_recency_boost(created_at: Optional[datetime]) -> float:
    """
    Boost score for recent resources.
    Resources created within RECENCY_BOOST_DAYS get up to +0.1 boost.
    """
    if not created_at:
        return 0.0
    
    try:
        days_old = (datetime.utcnow() - created_at).days
        if days_old <= RECENCY_BOOST_DAYS:
            # Linear decay: day 0 = +0.1, day 7 = 0
            boost = max(0, 0.1 * (1 - (days_old / RECENCY_BOOST_DAYS)))
            return round(boost, 3)
    except Exception as e:
        logger.debug(f"Recency calculation error: {e}")
    
    return 0.0


def _calculate_bloom_level_score(bloom_level: Optional[str], user_level: str) -> float:
    """
    Score based on Bloom taxonomy alignment with user level.
    Beginner learners prefer remember/understand
    Intermediate: understand/apply
    Advanced: apply/analyze/evaluate/create
    """
    if not bloom_level:
        return 0.0
    
    bloom_level = bloom_level.lower()
    
    preferences = {
        "beginner": {
            "remember": 0.9,
            "understand": 0.9,
            "apply": 0.6,
            "analyze": 0.3,
            "evaluate": 0.1,
            "create": 0.0
        },
        "intermediate": {
            "remember": 0.5,
            "understand": 0.9,
            "apply": 0.95,
            "analyze": 0.7,
            "evaluate": 0.5,
            "create": 0.3
        },
        "advanced": {
            "remember": 0.1,
            "understand": 0.5,
            "apply": 0.8,
            "analyze": 0.95,
            "evaluate": 0.95,
            "create": 0.95
        }
    }
    
    level_prefs = preferences.get(user_level.lower(), preferences["intermediate"])
    return level_prefs.get(bloom_level, 0.5)


def _calculate_pedagogy_score(pedagogy_type: Optional[str], user_level: str) -> float:
    """
    Score based on pedagogy type preference by level.
    Video > text > quiz for beginners
    Text > video > quiz for advanced
    """
    if not pedagogy_type:
        return 0.5
    
    pedagogy_type = pedagogy_type.lower()
    
    preferences = {
        "beginner": {
            "video": 0.95,
            "text": 0.7,
            "quiz": 0.5
        },
        "intermediate": {
            "video": 0.7,
            "text": 0.85,
            "quiz": 0.7
        },
        "advanced": {
            "video": 0.5,
            "text": 0.95,
            "quiz": 0.9
        }
    }
    
    level_prefs = preferences.get(user_level.lower(), preferences["intermediate"])
    return level_prefs.get(pedagogy_type, 0.5)


def _calculate_composite_score(
    semantic_score: float = 0.5,
    bloom_score: float = 0.5,
    pedagogy_score: float = 0.5,
    recency_score: float = 0.0
) -> float:
    """
    Calculate composite score from multiple signals.
    Weights: semantic (40%), bloom (30%), pedagogy (20%), recency (10%)
    """
    composite = (
        semantic_score * 0.40 +
        bloom_score * 0.30 +
        pedagogy_score * 0.20 +
        recency_score * 0.10
    )
    return round(min(1.0, max(0.0, composite)), 3)


# ==================================================
# MAIN RECOMMENDATION FUNCTION
# ==================================================
def recommend_resources_for_concept(
    concept_id: int,
    level: str,
    query: str = "",
    limit: int = 5,
    sort_by: str = "relevance"
) -> List[Dict]:
    """
    Recommend learning resources for a concept.
    
    Scoring factors (in order of importance):
    1. Semantic similarity to query (if provided)
    2. Bloom level alignment with user level
    3. Pedagogy type preference by level
    4. Resource recency (recent = better)
    5. Source priority (video > web > pdf > manual)
    
    Parameters
    ----------
    concept_id : int
        Concept to recommend resources for
    level : str
        User's current level (beginner/intermediate/advanced)
    query : str
        Optional query for semantic re-ranking
    limit : int
        Max number of recommendations (1-10)
    sort_by : str
        Sorting strategy: "relevance" | "recency" | "source"
    
    Returns
    -------
    List[Dict] : recommended resources with scores
    """
    
    db = get_db()
    limit = max(1, min(limit, MAX_RECOMMENDATIONS))
    
    logger.debug(
        f"Recommending resources: concept={concept_id}, level={level}, "
        f"query={query[:30] if query else 'none'}, limit={limit}"
    )
    
    # Validate inputs
    if not _validate_level(level):
        logger.warning(f"Invalid level '{level}'; using 'intermediate'")
        level = "intermediate"
    
    if not _validate_concept(db, concept_id):
        logger.warning(f"Concept {concept_id} not found; returning empty list")
        return []
    
    try:
        # Fetch resources for concept + level
        resources = list(db.resources.find(
            {
                "concept_id": concept_id,
                "level": level
            },
            {
                "_id": 1,
                "title": 1,
                "source": 1,
                "topic": 1,
                "level": 1,
                "url": 1,
                "embedding": 1,
                "bloom_level": 1,
                "pedagogy_type": 1,
                "created_at": 1,
                "has_transcript": 1
            }
        ))
        
        if not resources:
            logger.info(f"No resources found for concept {concept_id}, level {level}; trying fallback")
            # Fallback: try any level for this concept
            resources = list(db.resources.find(
                {"concept_id": concept_id},
                {
                    "_id": 1,
                    "title": 1,
                    "source": 1,
                    "topic": 1,
                    "level": 1,
                    "url": 1,
                    "embedding": 1,
                    "bloom_level": 1,
                    "pedagogy_type": 1,
                    "created_at": 1,
                    "has_transcript": 1
                }
            ).limit(20))  # Fetch more to filter later
            
            if not resources:
                logger.info(f"No resources found for concept {concept_id} at any level")
                return []
        
        logger.debug(f"Found {len(resources)} candidate resources for concept {concept_id}")
        
        # Score each resource
        scored_resources = []
        
        for resource in resources:
            try:
                # 1. Semantic similarity (if query provided)
                semantic_score = DEFAULT_SCORE
                if query:
                    try:
                        emb = resource.get("embedding")
                        if emb and len(emb) > 0:
                            query_vec = np.array(embed_text(query))
                            emb_arr = np.array(emb)
                            semantic_score = cosine_similarity(query_vec, emb_arr)
                    except Exception as e:
                        logger.debug(f"Semantic scoring error: {e}")
                
                # 2. Bloom level alignment
                bloom_score = _calculate_bloom_level_score(
                    resource.get("bloom_level"),
                    level
                )
                
                # 3. Pedagogy type preference
                pedagogy_score = _calculate_pedagogy_score(
                    resource.get("pedagogy_type"),
                    level
                )
                
                # 4. Recency boost
                recency_boost = _calculate_recency_boost(resource.get("created_at"))
                
                # 5. Composite score
                composite_score = _calculate_composite_score(
                    semantic_score=semantic_score,
                    bloom_score=bloom_score,
                    pedagogy_score=pedagogy_score,
                    recency_score=recency_boost
                )
                
                # Source priority
                source_priority = {
                    "youtube": 5,
                    "web": 4,
                    "pdf": 3,
                    "manual": 2
                }
                source_score = source_priority.get(resource.get("source", "manual"), 2) / 5
                
                scored_resources.append({
                    "resource_id": str(resource.get("_id")),
                    "title": resource.get("title"),
                    "source": resource.get("source"),
                    "topic": resource.get("topic"),
                    "level": resource.get("level"),
                    "url": resource.get("url"),
                    "pedagogy_type": resource.get("pedagogy_type"),
                    "bloom_level": resource.get("bloom_level"),
                    "has_transcript": resource.get("has_transcript", True),
                    "created_at": resource.get("created_at"),
                    # Scoring details
                    "semantic_score": round(semantic_score, 3),
                    "bloom_score": round(bloom_score, 3),
                    "pedagogy_score": round(pedagogy_score, 3),
                    "recency_boost": round(recency_boost, 3),
                    "source_score": round(source_score, 3),
                    "score": composite_score
                })
            
            except Exception as e:
                logger.debug(f"Error scoring resource {resource.get('_id')}: {e}")
                continue
        
        if not scored_resources:
            logger.warning(f"No resources could be scored for concept {concept_id}")
            return []
        
        # Sort by strategy
        if sort_by == "recency":
            scored_resources.sort(
                key=lambda x: (x["created_at"] or datetime.min),
                reverse=True
            )
        elif sort_by == "source":
            scored_resources.sort(
                key=lambda x: x["source_score"],
                reverse=True
            )
        else:  # "relevance" (default)
            scored_resources.sort(key=lambda x: x["score"], reverse=True)
        
        # Return top recommendations
        result = scored_resources[:limit]
        
        logger.info(
            f"Recommended {len(result)} resources for concept {concept_id}: "
            f"top_score={result[0]['score'] if result else 0}"
        )
        
        return result
    
    except Exception as e:
        logger.exception(f"Error recommending resources for concept {concept_id}: {e}")
        return []


# ==================================================
# BATCH RECOMMENDATIONS
# ==================================================
def recommend_resources_for_concepts(
    concept_ids: List[int],
    level: str,
    limit: int = 3
) -> Dict[int, List[Dict]]:
    """
    Batch recommend resources for multiple concepts.
    
    Parameters
    ----------
    concept_ids : List[int]
        List of concept IDs
    level : str
        User's level
    limit : int
        Resources per concept
    
    Returns
    -------
    Dict : {concept_id: [resources]}
    """
    results = {}
    
    for cid in concept_ids:
        try:
            resources = recommend_resources_for_concept(
                concept_id=cid,
                level=level,
                limit=limit
            )
            results[cid] = resources
        except Exception as e:
            logger.warning(f"Error recommending for concept {cid}: {e}")
            results[cid] = []
    
    return results


# ==================================================
# SOURCE FILTERING
# ==================================================
def filter_resources_by_source(
    resources: List[Dict],
    sources: List[str]
) -> List[Dict]:
    """Filter resources by source type(s)."""
    return [
        r for r in resources
        if r.get("source", "").lower() in [s.lower() for s in sources]
    ]


def filter_resources_by_bloom(
    resources: List[Dict],
    bloom_levels: List[str]
) -> List[Dict]:
    """Filter resources by Bloom taxonomy level(s)."""
    return [
        r for r in resources
        if r.get("bloom_level", "").lower() in [b.lower() for b in bloom_levels]
    ]


# ==================================================
# ANALYTICS
# ==================================================
def get_concept_resource_stats(concept_id: int) -> Dict:
    """Get statistics about resources for a concept."""
    db = get_db()
    
    try:
        resources = list(db.resources.find(
            {"concept_id": concept_id},
            {"level": 1, "source": 1, "pedagogy_type": 1}
        ))
        
        if not resources:
            return {"concept_id": concept_id, "total_resources": 0}
        
        # Count by level
        by_level = {}
        for r in resources:
            level = r.get("level", "unknown")
            by_level[level] = by_level.get(level, 0) + 1
        
        # Count by source
        by_source = {}
        for r in resources:
            source = r.get("source", "unknown")
            by_source[source] = by_source.get(source, 0) + 1
        
        # Count by pedagogy
        by_pedagogy = {}
        for r in resources:
            ptype = r.get("pedagogy_type", "unknown")
            by_pedagogy[ptype] = by_pedagogy.get(ptype, 0) + 1
        
        return {
            "concept_id": concept_id,
            "total_resources": len(resources),
            "by_level": by_level,
            "by_source": by_source,
            "by_pedagogy": by_pedagogy
        }
    
    except Exception as e:
        logger.exception(f"Error getting resource stats: {e}")
        return {"concept_id": concept_id, "error": str(e)}