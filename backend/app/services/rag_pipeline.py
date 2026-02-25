from typing import List, Dict, Optional
import os
import logging
import re
import time
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from backend.app.services.embedding_service import semantic_search

# ==================================================
# CONFIG
# ==================================================
USE_LLM = True
client = None

PRIMARY_MODEL = os.getenv("RAG_MODEL", "models/gemini-2.5-flash")
MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "2000"))
MAX_PROMPT_CHARS = int(os.getenv("RAG_MAX_PROMPT_CHARS", "8000"))
GENERATION_TIMEOUT = int(os.getenv("RAG_GENERATION_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("RAG_MAX_RETRIES", "2"))
MIN_RESOURCES = int(os.getenv("RAG_MIN_RESOURCES", "1"))
MAX_RESOURCES = int(os.getenv("RAG_MAX_RESOURCES", "10"))

# Try to initialize Gemini client
try:
    from google import genai
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info(f"✅ Gemini client initialized: model={PRIMARY_MODEL}")

except Exception as e:
    logger.warning("❌ Gemini init error: %s — LLM disabled, using retrieval-only mode", e)
    USE_LLM = False
    client = None


# ==================================================
# UTILITY FUNCTIONS
# ==================================================
@lru_cache(maxsize=256)
def _truncate_to_sentence(text: str, max_chars: int) -> str:
    """
    Truncate text to nearest sentence boundary.
    Cached for performance.
    """
    if len(text) <= max_chars:
        return text

    cutoff = text[:max_chars]
    
    # Try to find last sentence boundary
    boundaries = [
        cutoff.rfind(". "),
        cutoff.rfind("? "),
        cutoff.rfind("! "),
        cutoff.rfind(".\n"),
        cutoff.rfind("?\n"),
        cutoff.rfind("!\n"),
        cutoff.rfind("."),
        cutoff.rfind("?"),
        cutoff.rfind("!")
    ]
    
    last_idx = max(b for b in boundaries if b >= 0) if any(b >= 0 for b in boundaries) else -1
    
    if last_idx > 0:
        return cutoff[:last_idx + 1].strip()
    
    # Fallback: hard cut
    return cutoff.strip()


def _validate_input(question: str, goal: str) -> bool:
    """Validate RAG input parameters."""
    if not question or len(question) > 2000:
        logger.warning(f"Invalid question: len={len(question) if question else 0}")
        return False
    if not goal or len(goal) > 200:
        logger.warning(f"Invalid goal: len={len(goal) if goal else 0}")
        return False
    return True


# ==================================================
# RAG PIPELINE CLASS
# ==================================================
class RAGPipeline:
    """
    Retrieval-Augmented Generation (QA-RAG) Pipeline.
    
    Orchestrates: Retrieval → Context Building → Prompt Engineering → LLM Generation
    
    Features:
    - Semantic search with topic/level filtering
    - Context truncation respecting sentence boundaries
    - Robust LLM calling with multiple SDK shapes
    - Fallback to retrieval-only mode if LLM unavailable
    - Comprehensive logging and metrics
    - Configurable timeouts and retries
    """

    def __init__(self):
        self.stats = {
            "total_runs": 0,
            "successful_answers": 0,
            "retrieval_failures": 0,
            "llm_failures": 0,
            "fallback_uses": 0,
            "total_latency_ms": 0
        }

    # =========================
    # 1. RETRIEVE
    # =========================
    def retrieve_context(
        self,
        query: str,
        goal: Optional[str] = None,
        level: Optional[str] = None,
        k: int = 5
    ) -> List[Dict]:
        """
        Retrieve learning materials using semantic search.
        Falls back to default resources if search returns nothing.
        
        Parameters
        ----------
        query : str
            Question/search query
        goal : str
            Learning topic (for filtering)
        level : str
            Difficulty level (for filtering)
        k : int
            Number of resources to retrieve
        
        Returns
        -------
        List[Dict] : retrieved resources with scores
        """
        k = max(MIN_RESOURCES, min(k, MAX_RESOURCES))
        
        try:
            logger.debug(f"Retrieving: query={query[:50]}..., goal={goal}, level={level}, k={k}")
            
            resources = semantic_search(
                query=query,
                k=k,
                topic=goal,
                level=level,
                min_score=0.5  # Lower threshold for more results
            )
            
            logger.info(f"Retrieved {len(resources)} resources (requested {k})")
            
            # Fallback to default resources if nothing found
            if not resources and goal:
                logger.warning(f"No semantic search results for '{goal}' - using default resources")
                resources = self._get_default_resources(goal, level)
            
            return resources
        
        except Exception as e:
            logger.exception(f"Retrieval error: {e}")
            self.stats["retrieval_failures"] += 1
            # Try fallback default resources
            if goal:
                return self._get_default_resources(goal, level)
            return []

    def _get_default_resources(self, goal: Optional[str], level: Optional[str]) -> List[Dict]:
        """
        Return default resources when semantic search fails.
        Provides helpful general information about common topics.
        """
        default_kb = {
            "python": [
                {
                    "title": "Python Basics",
                    "snippet": "Python is a high-level, interpreted programming language known for its simplicity and readability. It uses indentation for code blocks and supports multiple programming paradigms including procedural, object-oriented, and functional programming.",
                    "score": 0.8,
                    "source": "knowledge_base"
                },
                {
                    "title": "Python Data Types",
                    "snippet": "Python supports various data types: int (integers), float (decimal numbers), str (text), bool (True/False), list (ordered collection), dict (key-value pairs), tuple (immutable sequence), and set (unique items). Each type has different characteristics and use cases.",
                    "score": 0.75,
                    "source": "knowledge_base"
                }
            ],
            "data science": [
                {
                    "title": "Data Science Fundamentals",
                    "snippet": "Data Science combines statistics, programming, and domain knowledge to extract insights from data. Key steps include: data collection, cleaning, exploration (EDA), visualization, modeling, and evaluation.",
                    "score": 0.8,
                    "source": "knowledge_base"
                }
            ],
            "web development": [
                {
                    "title": "Web Development Basics",
                    "snippet": "Web development involves building and maintaining websites. It includes frontend (user interface using HTML, CSS, JavaScript), backend (server logic), and databases. Modern web uses frameworks like React, Django, FastAPI.",
                    "score": 0.8,
                    "source": "knowledge_base"
                }
            ]
        }
        
        goal_key = (goal or "").lower()
        
        # Try to match goal with default resources
        for key, resources in default_kb.items():
            if key in goal_key:
                return resources
        
        # Generic fallback
        return [
            {
                "title": "Learning Tips",
                "snippet": "When learning a new topic: 1) Start with fundamentals and core concepts 2) Practice with hands-on examples 3) Build small projects 4) Review and reinforce 5) Connect to real-world applications. The more you practice, the better you understand.",
                "score": 0.7,
                "source": "knowledge_base"
            }
        ]

    # =========================
    # 2. BUILD CONTEXT
    # =========================
    def build_context(self, resources: List[Dict]) -> str:
        """
        Build limited-length context from retrieved resources.
        Respects sentence boundaries to avoid cutting mid-sentence.
        """
        if not resources:
            return "No learning materials found."

        blocks = []
        total_chars = 0

        for idx, r in enumerate(resources, start=1):
            try:
                title = r.get("title", "unknown")
                snippet = (r.get("snippet") or "").strip()
                score = r.get("score", 0)
                
                # Format source with ranking
                block = f"[Source {idx}: {title} (relevance: {score:.2f})]\n{snippet}"

                remaining = MAX_CONTEXT_CHARS - total_chars
                if remaining <= 0:
                    logger.debug(f"Context limit reached after {len(blocks)} resources")
                    break

                if len(block) > remaining:
                    # Truncate to fit
                    truncated = _truncate_to_sentence(block, remaining)
                    if truncated:
                        blocks.append(truncated)
                        total_chars += len(truncated)
                    break
                else:
                    blocks.append(block)
                    total_chars += len(block)
            
            except Exception as e:
                logger.debug(f"Error processing resource {idx}: {e}")
                continue

        context = "\n\n".join(blocks)
        logger.debug(f"Built context: {len(blocks)} blocks, {total_chars} chars")
        return context

    # =========================
    # 3. BUILD PROMPT
    # =========================
    def build_prompt(self, question: str, context: str) -> str:
        """
        Build RAG prompt with system instructions and context.
        """
        prompt = (
            "You are an AI tutor helping learners understand concepts.\n\n"
            "INSTRUCTIONS:\n"
            "1. Use ONLY the learning materials below to answer.\n"
            "2. Do NOT use outside knowledge or make up information.\n"
            "3. If you cannot find the answer in the materials, say:\n"
            "   'I cannot find the answer in the provided learning materials.'\n"
            "4. Be clear, concise, and appropriate for a beginner learner.\n"
            "\n"
            "LEARNING MATERIALS:\n"
            "====================\n"
            f"{context}\n"
            "====================\n\n"
            f"QUESTION:\n{question}\n\n"
            "ANSWER:"
        )
        
        # Validate prompt size
        if len(prompt) > MAX_PROMPT_CHARS:
            logger.warning(f"Prompt exceeds max size: {len(prompt)} > {MAX_PROMPT_CHARS}")
            # Truncate context if needed
            excess = len(prompt) - MAX_PROMPT_CHARS
            if excess > 0:
                context = _truncate_to_sentence(context, len(context) - excess - 500)
                prompt = self.build_prompt(question, context)
        
        return prompt

    # =========================
    # 4. GENERATE ANSWER
    # =========================
    def _extract_text_from_response(self, response) -> Optional[str]:
        """
        Robustly extract text from various SDK response shapes.
        """
        if response is None:
            return None

        try:
            # Try common direct fields
            if hasattr(response, "text") and isinstance(response.text, str):
                return response.text
            if hasattr(response, "output_text") and isinstance(response.output_text, str):
                return response.output_text

            # Try nested structures
            # response.output[0].content[0].text
            out = getattr(response, "output", None) or (response.get("output") if isinstance(response, dict) else None)
            if out and isinstance(out, (list, tuple)) and len(out) > 0:
                first = out[0]
                content = getattr(first, "content", None) or (first.get("content") if isinstance(first, dict) else None)
                if content and isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = getattr(piece, "text", None) or (piece.get("text") if isinstance(piece, dict) else None)
                    if isinstance(text, str):
                        return text

            # response.candidates[0].content[0].text
            cand = getattr(response, "candidates", None) or (response.get("candidates") if isinstance(response, dict) else None)
            if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                first = cand[0]
                content = first.get("content") if isinstance(first, dict) else getattr(first, "content", None)
                if content and isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = piece.get("text") if isinstance(piece, dict) else getattr(piece, "text", None)
                    if isinstance(text, str):
                        return text

            # response.choices[0].message.content
            choices = getattr(response, "choices", None) or (response.get("choices") if isinstance(response, dict) else None)
            if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
                first = choices[0]
                message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
                if message:
                    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
                    if isinstance(content, str):
                        return content
                    if isinstance(content, (list, tuple)) and len(content) > 0:
                        piece = content[0]
                        if isinstance(piece, str):
                            return piece

        except Exception as e:
            logger.debug(f"Text extraction error: {e}")

        return None

    def _call_llm_with_retry(self, prompt: str, retry_count: int = 0) -> Optional[str]:
        """
        Call LLM with retry logic.
        """
        if retry_count > MAX_RETRIES:
            logger.error(f"LLM call failed after {MAX_RETRIES} retries")
            return None

        try:
            logger.debug(f"LLM call attempt {retry_count + 1}/{MAX_RETRIES + 1}: model={PRIMARY_MODEL}")

            response = None

            # Preferred: Gemini SDK (genai.Client)
            if hasattr(client, "models") and hasattr(client.models, "generate_content"):
                response = client.models.generate_content(
                    model=PRIMARY_MODEL,
                    contents=prompt
                )
            elif hasattr(client, "generate"):
                response = client.generate(model=PRIMARY_MODEL, prompt=prompt)
            elif hasattr(client, "responses") and hasattr(client.responses, "create"):
                response = client.responses.create(model=PRIMARY_MODEL, input=prompt)
            else:
                raise AttributeError("No supported Gemini client method found")

            # Extract text
            text = self._extract_text_from_response(response)
            if text:
                logger.debug(f"LLM response received: {len(text)} chars")
                return text.strip()

            logger.warning("No text extracted from LLM response")
            return None

        except Exception as e:
            logger.warning(f"LLM call error (attempt {retry_count + 1}): {e}")
            if retry_count < MAX_RETRIES:
                time.sleep(1)  # Brief backoff before retry
                return self._call_llm_with_retry(prompt, retry_count + 1)
            
            self.stats["llm_failures"] += 1
            return None

    def generate(self, prompt: str) -> str:
        """
        Generate answer using LLM with safe fallback.
        """
        if not (USE_LLM and client):
            logger.info("LLM unavailable — using knowledge base fallback")
            self.stats["fallback_uses"] += 1
            return self._generate_fallback_answer(prompt)

        # Call LLM
        answer = self._call_llm_with_retry(prompt)
        
        if answer:
            self.stats["successful_answers"] += 1
            return answer

        # Fallback if LLM fails
        logger.warning("LLM generation failed — using knowledge base fallback")
        self.stats["fallback_uses"] += 1
        return self._generate_fallback_answer(prompt)

    def _generate_fallback_answer(self, prompt: str) -> str:
        """
        Generate answer using simple knowledge base when LLM unavailable.
        """
        # Extract context from prompt
        context_start = prompt.find("LEARNING MATERIALS:")
        if context_start > 0:
            context = prompt[context_start + 19:].strip()
            if context:
                return f"Based on the learning materials:\n\n{context}"
        
        # If no context, use predefined Q&A
        question_start = prompt.find("Question:")
        if question_start > 0:
            q_section = prompt[question_start:].split("\n")[0]
            question = q_section.replace("Question:", "").strip().lower()
            
            # Simple knowledge base
            kb = {
                "python": "Python is a high-level, interpreted programming language known for its simplicity and readability. It's widely used for web development, data analysis, machine learning, and automation.",
                "list": "In Python, a list is a mutable, ordered collection of items. You can create lists using square brackets: my_list = [1, 2, 3]. Lists support indexing, slicing, and various methods like append(), remove(), and sort().",
                "dict": "A dictionary in Python is an unordered collection of key-value pairs. You create dictionaries using curly braces: my_dict = {'key': 'value'}. Access values using their keys: my_dict['key'].",
                "function": "A function is a reusable block of code that performs a specific task. In Python, you define functions using the 'def' keyword: def my_function(): pass. Functions can take parameters and return values.",
                "loop": "Loops allow you to repeat a block of code multiple times. Python has 'for' loops for iterating over sequences and 'while' loops for conditional repetition.",
                "class": "A class is a blueprint for creating objects. It defines properties (attributes) and behaviors (methods). Classes are fundamental to object-oriented programming (OOP) in Python.",
            }
            
            # Try to match question to knowledge base
            for key, answer in kb.items():
                if key in question:
                    return answer
            
            # Generic fallback
            return (
                "I apologize, but I don't have specific learning materials for this question at the moment. "
                "However, I recommend:\n"
                "1. Check the Learning Path section for concepts related to your question\n"
                "2. Browse available Resources for tutorials and documentation\n"
                "3. Visit official documentation for detailed explanations"
            )
        
        return (
            "I'm having difficulty retrieving specific information for your question. "
            "Please try rephrasing your question or refer to the learning materials section."
        )

    # =========================
    # 5. RUN FULL PIPELINE
    # =========================
    def run(
        self,
        question: str,
        goal: str,
        level: str,
        completed: Optional[List[str]] = None
    ) -> Dict:
        """
        Execute full QA-RAG pipeline.
        """
        start_time = time.time()
        self.stats["total_runs"] += 1
        
        logger.info(f"RAG pipeline start: question={question[:60]}..., goal={goal}, level={level}")
        
        # Validate
        if not _validate_input(question, goal):
            return {
                "question": question,
                "answer": "Invalid input. Please provide a valid question and learning goal.",
                "sources": [],
                "error": "validation_failed"
            }

        try:
            # 1. Retrieve
            resources = self.retrieve_context(
                query=question,
                goal=goal,
                level=level,
                k=5
            )

            # 2. Build context
            context = self.build_context(resources)

            # 3. Build prompt
            prompt = self.build_prompt(question, context)

            # 4. Generate answer
            answer_text = self.generate(prompt)

            # 5. Return structured response
            elapsed_ms = (time.time() - start_time) * 1000
            self.stats["total_latency_ms"] += elapsed_ms
            
            logger.info(
                f"RAG pipeline complete: "
                f"resources={len(resources)}, "
                f"answer_len={len(answer_text)}, "
                f"latency={elapsed_ms:.1f}ms"
            )

            return {
                "success": True,
                "question": question,
                "answer": answer_text,
                "sources": [
                    {
                        "resource_id": r.get("resource_id"),
                        "title": r.get("title"),
                        "score": round(r.get("score", 0), 3),
                        "source": r.get("source")
                    }
                    for r in resources
                ],
                "latency_ms": round(elapsed_ms, 1)
            }

        except Exception as e:
            logger.exception(f"RAG pipeline error: {e}")
            return {
                "success": False,
                "question": question,
                "answer": "An error occurred while processing your question. Please try again.",
                "sources": [],
                "error": str(e)
            }

    # =========================
    # METRICS
    # =========================
    def get_stats(self) -> Dict:
        """Get pipeline statistics."""
        total = self.stats["total_runs"]
        if total > 0:
            success_rate = (self.stats["successful_answers"] / total) * 100
            avg_latency = self.stats["total_latency_ms"] / total
        else:
            success_rate = 0
            avg_latency = 0

        return {
            "total_runs": total,
            "successful_answers": self.stats["successful_answers"],
            "success_rate_percent": round(success_rate, 1),
            "llm_failures": self.stats["llm_failures"],
            "retrieval_failures": self.stats["retrieval_failures"],
            "fallback_uses": self.stats["fallback_uses"],
            "avg_latency_ms": round(avg_latency, 1),
            "total_latency_ms": round(self.stats["total_latency_ms"], 1)
        }