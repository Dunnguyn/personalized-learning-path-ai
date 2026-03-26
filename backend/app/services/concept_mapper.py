from typing import Optional, List, Dict
import logging
import re
import difflib

from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", text.lower()) if t]


def resolve_concept_id(
    topic: str, allow_fallback: bool = True, min_score: float = 0.40
) -> Optional[int]:
    """
    Map a free-form topic string -> best matching concept_id.

    Strategy (scoring):
      - exact topic match (weight 1.0)
      - exact concept_name match (weight 0.9)
      - substring matches (topic in concept.topic / concept_name) (weights 0.6 / 0.5)
      - token overlap (normalized) (weight 0.4)
      - fuzzy ratio between strings (weight 0.3)

    Returns:
      concept_id (int) if best score >= min_score,
      else if allow_fallback True returns easiest concept_id,
      otherwise None.
    """
    if not topic or not topic.strip():
        logger.debug("resolve_concept_id called with empty topic")
        return None

    db = get_db()
    topic_lower = topic.strip().lower()
    topic_tokens = set(_tokenize(topic_lower))

    try:
        concepts = list(
            db.concepts.find(
                {},
                {
                    "_id": 0,
                    "concept_id": 1,
                    "concept_name": 1,
                    "topic": 1,
                    "difficulty": 1,
                },
            )
        )
    except Exception as e:
        logger.exception("DB error fetching concepts: %s", e)
        return None

    if not concepts:
        logger.debug("No concepts found in DB")
        return None

    best = None
    best_score = 0.0

    for c in concepts:
        cid = c.get("concept_id")
        name = (c.get("concept_name") or "").strip().lower()
        top = (c.get("topic") or "").strip().lower()
        name_tokens = set(_tokenize(name))
        topic_field_tokens = set(_tokenize(top))

        score = 0.0

        # exact matches
        if topic_lower == top and top:
            score += 1.0
        if topic_lower == name and name:
            score += 0.9

        # substring matches
        if top and (topic_lower in top or top in topic_lower):
            score += 0.6
        if name and (topic_lower in name or name in topic_lower):
            score += 0.5

        # token overlap (normalized by topic token count)
        if topic_tokens:
            overlap = len(topic_tokens & (name_tokens | topic_field_tokens))
            token_score = (overlap / len(topic_tokens)) * 0.4
            score += token_score

        # fuzzy similarity between topic and concept name
        if name:
            ratio = difflib.SequenceMatcher(None, topic_lower, name).ratio()
            score += ratio * 0.3

        # normalize approximate score (cap)
        score = min(score, 1.0)

        if score > best_score:
            best_score = score
            best = {
                "concept_id": cid,
                "concept_name": c.get("concept_name"),
                "score": round(score, 3),
                "difficulty": c.get("difficulty", None),
            }

    logger.debug("Concept matching result for '%s': %s", topic, best)

    if best and best_score >= min_score:
        logger.info(
            "Resolved topic '%s' -> concept %s (score=%.3f)",
            topic,
            best["concept_name"],
            best_score,
        )
        return best["concept_id"]

    # No confident match
    if not allow_fallback:
        logger.info(
            "No confident concept match for '%s' (best_score=%.3f); allow_fallback=False -> returning None",
            topic,
            best_score,
        )
        return None

    # Fallback: return the easiest concept (lowest difficulty) if available
    try:
        concepts_with_diff = [
            c for c in concepts if isinstance(c.get("difficulty"), (int, float))
        ]
        if concepts_with_diff:
            easiest = min(concepts_with_diff, key=lambda x: x.get("difficulty", 99))
        else:
            easiest = concepts[0]
        logger.warning(
            "Falling back for topic '%s' to easiest concept %s (score=%.3f)",
            topic,
            easiest.get("concept_name"),
            best_score,
        )
        return easiest.get("concept_id")
    except Exception as e:
        logger.exception("Fallback selection error: %s", e)
        return None
