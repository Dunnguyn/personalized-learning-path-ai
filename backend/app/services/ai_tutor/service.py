from typing import List, Dict, Optional
import logging
import numpy as np
from time import perf_counter

from backend.app.services.ai_tutor.rag import RAGPipeline
from backend.app.services.progress_tracking.progress import (
    update_progress_with_confidence,
)
from backend.app.services.unified_learning_path_service import learning_path_service
from backend.app.services.embedding_service import embed_text, cosine_similarity
from backend.app.services.progress_tracking.confidence_scorer import score_confidence
from backend.app.services.adaptive_engine import (
    decide_learning_mode,
    filter_resources_by_mode,
    adaptive_decision_summary,
    LearningMode,
)
from backend.app.database.mongo import db

logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
MAX_RETRIES = 3
DEFAULT_CONCEPT_MATCH_THRESHOLD = 0.7
CONCEPT_CACHE_TTL = 3600  # 1 hour
CONCEPT_FALLBACK_DIFFICULTY = 5  # Use easiest concept if no match

# Global RAG instance
rag = RAGPipeline()


# =========================
# CONCEPT DETECTION (Semantic + Rule-based)
# =========================
class ConceptDetector:
    """
    Multi-strategy concept detection:
    1. Semantic search (embedding similarity)
    2. Rule-based keywords
    3. Fallback (easiest concept)
    """

    def __init__(self):
        self.keywords_map = self._build_keyword_map()
        self._concept_cache = {}
        self._has_concepts_cache: bool | None = None

    def _build_keyword_map(self) -> Dict[str, List[str]]:
        """
        Build rule-based keyword map for concept detection.
        Format: {concept_id: [keywords]}
        """
        # Load from DB for flexibility
        try:
            concepts = list(
                db.concepts.find({}, {"concept_id": 1, "concept_name": 1, "topic": 1})
            )

            keyword_map = {}
            for c in concepts:
                cid = c.get("concept_id")
                keywords = [
                    c.get("concept_name", "").lower(),
                    c.get("topic", "").lower(),
                ]
                # Add common variants
                name = c.get("concept_name", "").lower()
                if "list" in name:
                    keywords.extend(["array", "collection", "sequence"])
                if "dict" in name or "dictionary" in name:
                    keywords.extend(["map", "hash", "key-value"])
                if "loop" in name:
                    keywords.extend(["iteration", "for", "while", "repeat"])
                if "function" in name:
                    keywords.extend(["method", "procedure", "def"])
                if "class" in name or "oop" in name:
                    keywords.extend(["object", "inheritance", "encapsulation"])

                keyword_map[cid] = [k.strip() for k in keywords if k.strip()]

            logger.info(f"Keyword map built: {len(keyword_map)} concepts")
            return keyword_map

        except Exception as e:
            logger.warning(f"Failed to build keyword map: {e}")
            return {}

    def detect_semantic(
        self, question: str, threshold: float = DEFAULT_CONCEPT_MATCH_THRESHOLD
    ) -> Optional[Dict]:
        """
        Detect concept using semantic similarity (embedding).

        Returns:
            {concept_id, concept_name, score} or None
        """
        try:
            # Embed question
            q_vec = np.array(embed_text(question))

            # Fetch all concepts with embeddings
            concepts = list(
                db.concepts.find(
                    {"embedding": {"$exists": True}},
                    {"concept_id": 1, "concept_name": 1, "embedding": 1},
                )
            )

            if not concepts:
                logger.debug("No concepts with embeddings found")
                return None

            # Score each concept
            best_match = None
            best_score = 0

            for concept in concepts:
                c_vec = np.array(concept.get("embedding", []))

                if len(c_vec) == 0:
                    continue

                try:
                    score = cosine_similarity(q_vec, c_vec)

                    if score > best_score:
                        best_score = score
                        best_match = {
                            "concept_id": concept.get("concept_id"),
                            "concept_name": concept.get("concept_name"),
                            "score": round(score, 3),
                        }
                except Exception as e:
                    logger.debug(f"Similarity calc error: {e}")
                    continue

            if best_match and best_score >= threshold:
                logger.info(
                    f"Semantic detection: '{question[:50]}...' → "
                    f"{best_match['concept_name']} (score={best_score:.3f})"
                )
                return best_match

            return None

        except Exception as e:
            logger.exception(f"Semantic detection error: {e}")
            return None

    def detect_rule_based(self, question: str) -> Optional[Dict]:
        """
        Detect concept using rule-based keyword matching.

        Returns:
            {concept_id, concept_name, method: "rule-based"} or None
        """
        if not self.keywords_map:
            return None

        q_lower = question.lower()
        best_match = None
        max_keywords_matched = 0

        for cid, keywords in self.keywords_map.items():
            matched_count = sum(1 for kw in keywords if kw in q_lower)

            if matched_count > max_keywords_matched:
                max_keywords_matched = matched_count

                concept = db.concepts.find_one({"concept_id": cid})
                if concept:
                    best_match = {
                        "concept_id": cid,
                        "concept_name": concept.get("concept_name"),
                        "method": "rule-based",
                        "matched_keywords": matched_count,
                    }

        if best_match and best_match["matched_keywords"] > 0:
            logger.info(
                f"Rule-based detection: '{question[:50]}...' → "
                f"{best_match['concept_name']} ({best_match['matched_keywords']} keywords)"
            )
            return best_match

        return None

    def detect_fallback(self) -> Optional[Dict]:
        """
        Fallback: return easiest concept.
        """
        try:
            easiest = db.concepts.find_one(
                {}, {"concept_id": 1, "concept_name": 1, "difficulty": 1}
            )

            if not easiest:
                logger.info("Concept detection skipped: no concepts found in database")
                return None

            logger.warning(f"Using fallback concept: {easiest['concept_name']}")
            return {
                "concept_id": easiest["concept_id"],
                "concept_name": easiest["concept_name"],
                "method": "fallback",
            }

        except Exception as e:
            logger.exception(f"Fallback detection error: {e}")
            return None

    def detect(self, question: str) -> Optional[Dict]:
        """
        Multi-strategy concept detection pipeline:
        1. Semantic (embedding similarity)
        2. Rule-based (keyword matching)
        3. Fallback (easiest concept)

        Parameters
        ----------
        question : str
            Learner's question

        Returns
        -------
        Dict : {concept_id, concept_name, method, ...} or None
        """

        if not question or not question.strip():
            return None
        if not self._has_any_concepts():
            logger.info("Concept detection unavailable: concept catalog is empty")
            return None

        # Strategy 1: Semantic
        result = self.detect_semantic(question)
        if result:
            return result

        # Strategy 2: Rule-based
        result = self.detect_rule_based(question)
        if result:
            return result

        # Strategy 3: Fallback
        result = self.detect_fallback()
        if result:
            return result

        logger.info(f"Could not detect concept for: '{question[:100]}'")
        return None

    def _has_any_concepts(self) -> bool:
        if self._has_concepts_cache is not None:
            return self._has_concepts_cache
        try:
            self._has_concepts_cache = bool(db.concepts.find_one({}, {"concept_id": 1}))
        except Exception as exc:
            logger.warning("Could not inspect concept catalog: %s", exc)
            self._has_concepts_cache = False
        return self._has_concepts_cache


# Initialize detector
concept_detector = ConceptDetector()


# =========================
# ORCHESTRATION SERVICE
# =========================
class AITutorService:
    """
    Core AI tutoring orchestration service.
    Coordinates: RAG → progress → adaptive engine → learning path
    """

    def __init__(self):
        self.rag = RAGPipeline()
        self.detector = concept_detector

    def ask_ai(
        self,
        user_id: str,
        question: str,
        goal: str,
        level: str,
        subject_id: Optional[str] = None,
        completed: Optional[List[str]] = None,
        retry_count: int = 0,
    ) -> Dict:
        """
        Main AI tutoring method - full orchestration.

        Pipeline:
        1. RAG - get answer + context
        2. Confidence scoring - evaluate answer quality
        3. Concept detection - match to learning concept
        4. Progress update - EMA-based mastery update
        5. Adaptive decision - determine learning mode
        6. Learning path - generate next recommendations

        Parameters
        ----------
        user_id : str
            User ID (MongoDB ObjectId as string)
        question : str
            Learner's question
        goal : str
            Learning goal/topic
        level : str
            Current level (beginner/intermediate/advanced)
        completed : List[str]
            List of completed concept IDs
        retry_count : int
            Internal retry counter

        Returns
        -------
        Dict : full response with answer, path, adaptive info
        """

        total_started_at = perf_counter()
        timings: Dict[str, float] = {}

        logger.info(
            f"ASK: user={user_id}, goal={goal}, level={level}, "
            f"question_len={len(question)}"
        )

        try:
            # ===== 1. RAG ANSWER =====
            rag_result = self._get_rag_answer(
                question,
                goal,
                level,
                completed or [],
                timings=timings,
            )
            answer_text = rag_result.get("answer", "")
            sources = rag_result.get("sources", [])
            answer_method = rag_result.get(
                "answer_method", "unknown"
            )  # direct_from_context or ai_generated

            # ===== 2. CONFIDENCE SCORING =====
            confidence = self._score_confidence(question, answer_text)

            # ===== 3. CONCEPT DETECTION =====
            concept_info = self.detector.detect(question)

            # ===== 4. PROGRESS UPDATE =====
            progress_updated = False
            current_mastery = 0.0
            current_attempts = 0

            if concept_info:
                progress_updated, current_mastery, current_attempts = (
                    self._update_progress(
                        user_id=user_id,
                        concept_id=concept_info["concept_id"],
                        confidence=confidence,
                    )
                )

            # ===== 5. ADAPTIVE DECISION =====
            adaptive_info = None
            learning_mode = LearningMode.NORMAL.value

            if progress_updated:
                adaptive_info = adaptive_decision_summary(
                    mastery=current_mastery,
                    confidence=confidence,
                    total_attempts=current_attempts,
                )
                learning_mode = adaptive_info.get("mode", LearningMode.NORMAL.value)

            # ===== 6. LEARNING PATH =====
            learning_path = self._generate_adaptive_path(
                user_id=user_id,
                goal=goal,
                level=level,
                subject_id=subject_id,
                learning_mode=learning_mode,
            )

            # ===== 7. RESPONSE =====
            response = {
                "success": True,
                "answer": {
                    "answer_text": answer_text,
                    "answer_method": answer_method,  # direct_from_context or ai_generated
                    "confidence": round(confidence, 3),
                    "sources": sources,
                },
                "learning_path": learning_path,
                "concept_detected": {
                    "concept_id": (
                        concept_info.get("concept_id") if concept_info else None
                    ),
                    "concept_name": (
                        concept_info.get("concept_name") if concept_info else None
                    ),
                    "score": concept_info.get("score") if concept_info else None,
                },
                "adaptive_info": adaptive_info,
                "progress_updated": progress_updated,
                "processing_metrics": {
                    **rag_result.get("timings", {}),
                    **timings,
                    "total_ai_response_ms": round(
                        (perf_counter() - total_started_at) * 1000.0,
                        3,
                    ),
                },
            }

            logger.info(f"Ask completed: user={user_id}")
            return response

        except Exception as e:
            logger.exception(f"Error in ask_ai (retry {retry_count}): {e}")

            # Retry logic
            if retry_count < MAX_RETRIES:
                logger.info(
                    f"Retrying ask_ai (attempt {retry_count + 1}/{MAX_RETRIES})"
                )
                return self.ask_ai(
                    user_id=user_id,
                    question=question,
                    goal=goal,
                    level=level,
                    subject_id=subject_id,
                    completed=completed,
                    retry_count=retry_count + 1,
                )

            # Final fallback
            logger.error(f"ask_ai failed after {MAX_RETRIES} retries")
            return {
                "success": False,
                "answer": {
                    "answer_text": "Xin lỗi, tôi gặp sự cố khi xử lý câu hỏi của bạn. Vui lòng thử lại.",
                    "answer_method": "error",
                    "confidence": 0.0,
                    "sources": [],
                },
                "learning_path": [],
                "concept_detected": None,
                "adaptive_info": None,
                "progress_updated": False,
            }

    def _get_rag_answer(
        self,
        question: str,
        goal: str,
        level: str,
        completed: List[str],
        timings: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Get RAG-based answer with fallback"""
        try:
            return self.rag.run(
                question=question,
                goal=goal,
                level=level,
                completed=completed,
                timings=timings,
            )
        except Exception as e:
            logger.exception(f"RAG error: {e}")
            return {
                "answer": "I couldn't retrieve an answer at the moment. Please check the learning materials.",
                "sources": [],
            }

    def _score_confidence(self, question: str, answer: str) -> float:
        """Score answer confidence with fallback"""
        try:
            return score_confidence(question, answer)
        except Exception as e:
            logger.warning(f"Confidence scoring error: {e}")
            return 0.5  # Conservative fallback

    def _update_progress(
        self, user_id: int, concept_id: int, confidence: float
    ) -> tuple:
        """Update progress and return (success, mastery, attempts)"""
        try:
            # Get current progress
            progress = db.progress.find_one(
                {"user_id": user_id, "concept_id": concept_id}
            )
            current_attempts = progress.get("total_attempts", 0) if progress else 0

            # Update
            mastery = update_progress_with_confidence(
                user_id=user_id, concept_id=concept_id, confidence=confidence
            )

            logger.info(
                f"Progress updated: user={user_id}, concept={concept_id}, "
                f"mastery={mastery}, attempts={current_attempts + 1}"
            )

            return True, mastery, current_attempts + 1

        except Exception as e:
            logger.exception(f"Progress update error: {e}")
            return False, 0.0, 0

    def _generate_adaptive_path(
        self,
        user_id: int,
        goal: str,
        level: str,
        subject_id: Optional[str],
        learning_mode: str,
    ) -> List[Dict]:
        """Return recommendations from an existing path only.

        AI Tutor must not generate new learning paths or mutate the subject catalog
        as a side effect of answering a question.
        """
        try:
            recommended_path = learning_path_service.recommend_next_concepts(
                user_id=str(user_id),
                goal=goal,
                level=level,
                subject_id=subject_id,
                limit=15,
                allow_generate=False,
            )

            # Apply adaptive filtering by learning mode
            if learning_mode:
                try:
                    mode_enum = LearningMode(learning_mode)

                    for item in recommended_path:
                        if "resources" in item and item["resources"]:
                            filtered = filter_resources_by_mode(
                                item["resources"], mode_enum
                            )
                            item["resources"] = filtered[:5]  # Top 5

                except Exception as e:
                    logger.warning(f"Resource filtering error: {e}")

            return recommended_path

        except Exception as e:
            logger.exception(f"Learning path recommendation error: {e}")
            return []


# =========================
# SINGLETON INSTANCE
# =========================
ai_tutor_service = AITutorService()


# =========================
# CONVENIENCE FUNCTION (backward compatibility)
# =========================
def ask_ai_service(
    user_id: int,
    question: str,
    goal: str,
    level: str,
    subject_id: Optional[str] = None,
    completed: Optional[List[str]] = None,
) -> Dict:
    """
    Convenience wrapper for ask_ai.
    (Backward compatible with old API)
    """
    return ai_tutor_service.ask_ai(
        user_id=user_id,
        question=question,
        goal=goal,
        level=level,
        subject_id=subject_id,
        completed=completed,
    )


# =========================
# OPTIONAL: BATCH CONCEPT DETECTION
# =========================
def detect_concepts_batch(questions: List[str]) -> List[Optional[Dict]]:
    """
    Detect concepts for multiple questions in batch.
    Useful for batch processing or pre-analysis.

    Parameters
    ----------
    questions : List[str]
        List of questions

    Returns
    -------
    List[Optional[Dict]] : concept detections (may contain None for failures)
    """
    logger.info(f"Batch concept detection: {len(questions)} questions")

    results = []
    for question in questions:
        try:
            detected = concept_detector.detect(question)
            results.append(detected)
        except Exception as e:
            logger.warning(f"Batch detection error: {e}")
            results.append(None)

    return results


# =========================
# OPTIONAL: CONCEPT RECOMMENDATION (without full QA)
# =========================
def recommend_next_concepts(
    user_id: int,
    goal: str,
    level: str,
    limit: int = 5,
    subject_id: Optional[str] = None,
) -> Dict:
    """
    Recommend next concepts to study without answering a question.
    Useful for browsing/exploring.
    """
    try:
        recommended = learning_path_service.recommend_next_concepts(
            user_id=str(user_id),
            goal=goal,
            level=level,
            subject_id=subject_id,
            limit=limit,
        )

        logger.info(
            f"Next concepts recommended: user={user_id}, count={len(recommended)}"
        )

        return {"success": True, "recommended_concepts": recommended}

    except Exception as e:
        logger.exception(f"Concept recommendation error: {e}")
        return {"success": False, "error": str(e), "recommended_concepts": []}
