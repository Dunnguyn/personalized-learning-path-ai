from typing import List, Dict, Optional
import os
import logging
import re
import time
from time import perf_counter
from functools import lru_cache

from backend.app.services.ai_tutor.answer_generation import (
    generate_answer as generate_ai_tutor_answer,
    generate_fallback_answer as generate_ai_tutor_fallback_answer,
)
from backend.app.services.ai_tutor.citation_mapping import (
    can_answer_from_context as can_answer_ai_tutor_from_context,
    generate_direct_answer as generate_ai_tutor_direct_answer,
)
from backend.app.services.ai_tutor.post_response_actions import (
    build_fallback_context as build_ai_tutor_fallback_context,
    format_answer_beautifully as format_ai_tutor_answer,
)
from backend.app.services.ai_tutor.prompting import (
    build_context as build_ai_tutor_context,
    build_prompt as build_ai_tutor_prompt,
)
from backend.app.utils.gemini import get_gemini_client, get_gemini_client_manager
from backend.app.utils.performance import add_timing

logger = logging.getLogger(__name__)

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
RETRIEVAL_K = int(os.getenv("RAG_RETRIEVAL_K", "8"))
RETRIEVAL_MIN_SCORE = float(os.getenv("RAG_RETRIEVAL_MIN_SCORE", "0.35"))
QUOTA_COOLDOWN_SECONDS = int(os.getenv("RAG_QUOTA_COOLDOWN_SECONDS", "120"))
LLM_COOLDOWN_UNTIL = 0.0

# Ngưỡng để quyết định có thể trả lời trực tiếp từ context hay cần dùng AI
# Tăng threshold cao hơn để chỉ trả lời trực tiếp khi RẤT chắc chắn
DIRECT_ANSWER_THRESHOLD = float(
    os.getenv("RAG_DIRECT_ANSWER_THRESHOLD", "0.80")
)  # Tăng từ 0.70 → 0.80
MIN_HIGH_QUALITY_RESOURCES = int(
    os.getenv("RAG_MIN_HIGH_QUALITY_RESOURCES", "2")
)  # Tăng từ 1 → 2

# Try to initialize Gemini client
try:
    client = get_gemini_client()
    if client is None:
        raise ValueError("Gemini API key not set")
    logger.info(f"✅ Gemini client initialized: model={PRIMARY_MODEL}")

except Exception as e:
    logger.warning(
        "❌ Gemini init error: %s — LLM disabled, using retrieval-only mode", e
    )
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
        cutoff.rfind("!"),
    ]

    last_idx = (
        max(b for b in boundaries if b >= 0) if any(b >= 0 for b in boundaries) else -1
    )

    if last_idx > 0:
        return cutoff[: last_idx + 1].strip()

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


def _get_quota_cooldown_seconds(error: Exception) -> Optional[int]:
    """Return cooldown seconds if error indicates quota exhaustion."""
    text = str(error)
    if "RESOURCE_EXHAUSTED" in text or "Quota exceeded" in text or "429" in text:
        match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", text, re.IGNORECASE)
        if not match:
            match = re.search(r"retryDelay': '([0-9]+)s'", text)
        if match:
            return int(float(match.group(1)))
        return QUOTA_COOLDOWN_SECONDS
    return None


def _rag_scope_retry_after_seconds() -> float:
    status = get_gemini_client_manager().get_scope_status(
        scope=f"generate_content:{PRIMARY_MODEL}"
    )
    return max(0.0, float(status.get("retry_after_seconds", 0.0) or 0.0))


def _keyword_overlap_score(question: str, text: str) -> int:
    """Simple lexical overlap score to keep fallback answers on-topic."""
    if not question or not text:
        return 0

    tokens_q = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
    tokens_t = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))

    stop = {
        "la",
        "gi",
        "what",
        "is",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "lao",
        "hoc",
        "lap",
        "trinh",
        "cua",
        "ve",
        "about",
        "how",
        "why",
        "khi",
        "nao",
        "nhu",
        "theo",
    }
    tokens_q = {t for t in tokens_q if t not in stop}
    tokens_t = {t for t in tokens_t if t not in stop}

    if not tokens_q or not tokens_t:
        return 0

    return len(tokens_q & tokens_t)


def _is_definition_question(question: str) -> bool:
    if not question:
        return False
    q = question.lower()
    triggers = ["what is", "what's", "la gi", "là gì", "dinh nghia", "định nghĩa"]
    return any(t in q for t in triggers)


def _extract_main_terms(question: str) -> List[str]:
    if not question:
        return []
    tokens = re.findall(r"[a-zA-Z0-9_]+", question.lower())
    stop = {
        "la",
        "gi",
        "what",
        "is",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "hoc",
        "lap",
        "trinh",
        "cua",
        "ve",
        "about",
        "how",
        "why",
        "khi",
        "nao",
        "nhu",
        "theo",
    }
    return [t for t in tokens if t not in stop]


def _find_definition_sentence(terms: List[str], text: str) -> str:
    """Return a sentence that defines the main term, if found."""
    if not terms or not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    for sentence in sentences:
        s_lower = sentence.lower()
        has_term = any(term in s_lower for term in terms)
        if not has_term:
            continue
        if (
            " is " in s_lower
            or " la " in s_lower
            or " là " in s_lower
            or " means " in s_lower
        ):
            return sentence.strip()

    return ""


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
            "direct_answers": 0,
            "ai_answers": 0,
            "total_latency_ms": 0,
        }
        self._last_generation_mode = "unknown"

    # =========================
    # 1. RETRIEVE
    # =========================
    def retrieve_context(
        self,
        query: str,
        goal: Optional[str] = None,
        level: Optional[str] = None,
        k: int = 5,
        timings: Optional[Dict[str, float]] = None,
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
            started_at = perf_counter()
            logger.debug(
                f"Retrieving: query={query[:50]}..., goal={goal}, level={level}, k={k}"
            )

            # Note: Don't pass goal as topic filter because goal might be in Vietnamese
            # while database topics are in English. Let semantic search handle it via similarity.
            resources = semantic_search(
                query=query,
                k=k,
                topic=None,  # Disabled topic filter to allow semantic matching
                level=level,
                min_score=RETRIEVAL_MIN_SCORE,
                timings=timings,
            )

            add_timing(timings, "retrieval_total_ms", perf_counter() - started_at)

            logger.info(
                f"Retrieved {len(resources)} resources from database (requested {k})"
            )

            # Đánh dấu nguồn gốc tài liệu
            for r in resources:
                r["is_real_resource"] = True  # Từ database thực

            # KHÔNG fallback ở đây - để AI xử lý nếu không có tài liệu thực
            if not resources:
                logger.warning(
                    f"⚠️  No resources found in database for '{goal}' - AI will be used"
                )

            return resources

        except Exception as e:
            logger.exception(f"Retrieval error: {e}")
            self.stats["retrieval_failures"] += 1
            # Try fallback default resources
            if goal:
                return self._get_default_resources(goal, level)
            return []

    def _get_default_resources(
        self, goal: Optional[str], level: Optional[str]
    ) -> List[Dict]:
        """
        Return default resources when semantic search fails.
        Provides helpful general information about common topics.
        """
        default_kb = [
            (
                "backend",
                [
                    {
                        "title": "Backend Development Basics",
                        "snippet": "Backend là phần xử lý phía máy chủ của một ứng dụng. Nó chịu trách nhiệm nhận request từ client, xử lý logic nghiệp vụ, làm việc với cơ sở dữ liệu, xác thực người dùng và trả response về cho frontend qua API.",
                        "score": 0.86,
                        "source": "knowledge_base",
                    },
                    {
                        "title": "Backend Components",
                        "snippet": "Một hệ thống backend thường gồm API routes, business logic, database access, authentication và integration với dịch vụ bên ngoài. Các framework phổ biến gồm FastAPI, Django, Express và Spring Boot.",
                        "score": 0.82,
                        "source": "knowledge_base",
                    },
                ],
            ),
            (
                "fastapi",
                [
                    {
                        "title": "FastAPI Overview",
                        "snippet": "FastAPI là framework Python để xây dựng backend API hiện đại. Nó hỗ trợ type hints, validation bằng Pydantic, tài liệu Swagger tự động và hiệu năng cao nhờ ASGI.",
                        "score": 0.84,
                        "source": "knowledge_base",
                    }
                ],
            ),
            (
                "web development",
                [
                    {
                        "title": "Web Development Basics",
                        "snippet": "Web development bao gồm frontend và backend. Frontend xử lý giao diện người dùng, còn backend xử lý logic phía server, dữ liệu và API kết nối với frontend.",
                        "score": 0.8,
                        "source": "knowledge_base",
                    }
                ],
            ),
            (
                "python",
                [
                    {
                        "title": "Python Basics",
                        "snippet": "Python is a high-level, interpreted programming language known for its simplicity and readability. It uses indentation for code blocks and supports multiple programming paradigms including procedural, object-oriented, and functional programming.",
                        "score": 0.8,
                        "source": "knowledge_base",
                    },
                    {
                        "title": "Python Data Types",
                        "snippet": "Python supports various data types: int (integers), float (decimal numbers), str (text), bool (True/False), list (ordered collection), dict (key-value pairs), tuple (immutable sequence), and set (unique items). Each type has different characteristics and use cases.",
                        "score": 0.75,
                        "source": "knowledge_base",
                    },
                ],
            ),
            (
                "data science",
                [
                    {
                        "title": "Data Science Fundamentals",
                        "snippet": "Data Science combines statistics, programming, and domain knowledge to extract insights from data. Key steps include: data collection, cleaning, exploration (EDA), visualization, modeling, and evaluation.",
                        "score": 0.8,
                        "source": "knowledge_base",
                    }
                ],
            ),
        ]

        goal_key = (goal or "").lower()

        # Try to match goal with default resources
        for key, resources in default_kb:
            if key in goal_key:
                return resources

        # Generic fallback
        return [
            {
                "title": "Learning Tips",
                "snippet": "When learning a new topic: 1) Start with fundamentals and core concepts 2) Practice with hands-on examples 3) Build small projects 4) Review and reinforce 5) Connect to real-world applications. The more you practice, the better you understand.",
                "score": 0.7,
                "source": "knowledge_base",
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
        Optimized for focused and coherent answers that directly address the question.
        AI will output markdown formatted text for better UI presentation.
        """
        # Kiểm tra xem có phải context từ fallback không
        is_fallback = "[Lưu ý: Đây là thông tin từ knowledge base mặc định" in context

        if (
            is_fallback
            or not context
            or context == "Không có thông tin cụ thể trong hệ thống."
        ):
            # Prompt cho trường hợp không có tài liệu thực
            prompt = (
                "Bạn là AI Tutor - trợ lý học tập thông minh.\n\n"
                "ĐỊNH DẠNG CÂU TRẢ LỜI:\n"
                "- Sử dụng Markdown để format câu trả lời\n"
                "- Sử dụng ## để tạo tiêu đề\n"
                "- Sử dụng **text** để làm đậm\n"
                "- Sử dụng - để tạo danh sách bullet\n"
                "- Tách các phần bằng dòng trống\n\n"
                "NHIỆM VỤ CHÍNH:\n"
                "Trả lời TRỰC TIẾP và TẬP TRUNG vào câu hỏi của người học.\n"
                "- Tập trung vào cái được hỏi, không lạc đi\n"
                "- Trả lời rõ ràng, chi tiết, dễ hiểu\n"
                "- Phù hợp với người mới bắt đầu học\n"
                "- Cung cấp ví dụ cụ thể khi cần\n"
                "- Tránh thông tin không liên quan\n\n"
                f"CÂU HỎI:\n{question}\n\n"
                "CÂU TRẢ LỜI (dùng Markdown):"
            )
        else:
            # Prompt tiêu chuẩn khi có tài liệu thực - cải thiện rõ ràng hơn
            prompt = (
                "Bạn là AI Tutor - trợ lý học tập thông minh.\n\n"
                "ĐỊNH DẠNG CÂU TRẢ LỜI:\n"
                "- Sử dụng Markdown để format câu trả lời\n"
                "- Sử dụng ## để tạo tiêu đề\n"
                "- Sử dụng **text** để làm đậm\n"
                "- Sử dụng - để tạo danh sách bullet\n"
                "- Tách các phần bằng dòng trống\n\n"
                "NHIỆM VỤ CHÍNH:\n"
                "Trả lời TRỰC TIẾP vào câu hỏi của người học dựa trên tài liệu cung cấp.\n"
                "Quy tắc:\n"
                "1. TẬP TRUNG vào câu hỏi - trả lời CHỈ những gì được hỏi\n"
                "2. Sử dụng tài liệu làm bằng chứng chính\n"
                "3. Bổ sung kiến thức nếu tài liệu không đủ chi tiết\n"
                "4. Giải thích rõ ràng, dễ hiểu, phù hợp với người mới bắt đầu\n"
                "5. Cung cấp ví dụ cụ thể khi cần\n"
                "6. TRÁNH lạc đi vào chi tiết không liên quan\n\n"
                "TÀI LIỆU HỌC TẬP:\n"
                "====================\n"
                f"{context}\n"
                "====================\n\n"
                f"CÂU HỎI CỦA NGƯỜI HỌC:\n{question}\n\n"
                "CÂU TRẢ LỜI (dùng Markdown):"
            )

        # Validate prompt size
        if len(prompt) > MAX_PROMPT_CHARS:
            logger.warning(
                f"Prompt exceeds max size: {len(prompt)} > {MAX_PROMPT_CHARS}"
            )
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
            if hasattr(response, "output_text") and isinstance(
                response.output_text, str
            ):
                return response.output_text

            # Try nested structures
            # response.output[0].content[0].text
            out = getattr(response, "output", None) or (
                response.get("output") if isinstance(response, dict) else None
            )
            if out and isinstance(out, (list, tuple)) and len(out) > 0:
                first = out[0]
                content = getattr(first, "content", None) or (
                    first.get("content") if isinstance(first, dict) else None
                )
                if content and isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = getattr(piece, "text", None) or (
                        piece.get("text") if isinstance(piece, dict) else None
                    )
                    if isinstance(text, str):
                        return text

            # response.candidates[0].content[0].text
            cand = getattr(response, "candidates", None) or (
                response.get("candidates") if isinstance(response, dict) else None
            )
            if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                first = cand[0]
                content = (
                    first.get("content")
                    if isinstance(first, dict)
                    else getattr(first, "content", None)
                )
                if content and isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = (
                        piece.get("text")
                        if isinstance(piece, dict)
                        else getattr(piece, "text", None)
                    )
                    if isinstance(text, str):
                        return text

            # response.choices[0].message.content
            choices = getattr(response, "choices", None) or (
                response.get("choices") if isinstance(response, dict) else None
            )
            if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
                first = choices[0]
                message = (
                    first.get("message")
                    if isinstance(first, dict)
                    else getattr(first, "message", None)
                )
                if message:
                    content = (
                        message.get("content")
                        if isinstance(message, dict)
                        else getattr(message, "content", None)
                    )
                    if isinstance(content, str):
                        return content
                    if isinstance(content, (list, tuple)) and len(content) > 0:
                        piece = content[0]
                        if isinstance(piece, str):
                            return piece

        except Exception as e:
            logger.debug(f"Text extraction error: {e}")

        return None

    def _call_llm_with_retry(
        self,
        prompt: str,
        retry_count: int = 0,
        timings: Optional[Dict[str, float]] = None,
    ) -> Optional[str]:
        """
        Call LLM with retry logic.
        """
        if retry_count > MAX_RETRIES:
            logger.error(f"LLM call failed after {MAX_RETRIES} retries")
            return None
        if _rag_scope_retry_after_seconds() > 0:
            logger.info("RAG LLM skipped because Gemini scope is cooling down.")
            return None

        try:
            logger.debug(
                f"LLM call attempt {retry_count + 1}/{MAX_RETRIES + 1}: model={PRIMARY_MODEL}"
            )

            response = None
            call_started = perf_counter()

            # Preferred: Gemini SDK (genai.Client)
            if hasattr(client, "models") and hasattr(client.models, "generate_content"):
                response = client.models.generate_content(
                    model=PRIMARY_MODEL, contents=prompt
                )
            elif hasattr(client, "generate"):
                response = client.generate(model=PRIMARY_MODEL, prompt=prompt)
            elif hasattr(client, "responses") and hasattr(client.responses, "create"):
                response = client.responses.create(model=PRIMARY_MODEL, input=prompt)
            else:
                raise AttributeError("No supported Gemini client method found")

            # Extract text
            text = self._extract_text_from_response(response)
            add_timing(timings, "gemini_generation_ms", perf_counter() - call_started)
            if text:
                logger.debug(f"LLM response received: {len(text)} chars")
                return text.strip()

            logger.warning("No text extracted from LLM response")
            return None

        except Exception as e:
            logger.warning(f"LLM call error (attempt {retry_count + 1}): {e}")
            cooldown = _get_quota_cooldown_seconds(e)
            if cooldown is not None:
                global LLM_COOLDOWN_UNTIL
                LLM_COOLDOWN_UNTIL = time.time() + max(QUOTA_COOLDOWN_SECONDS, cooldown)
                logger.warning(
                    "LLM quota exhausted; cooldown active for %ss",
                    max(QUOTA_COOLDOWN_SECONDS, cooldown),
                )
                self.stats["llm_failures"] += 1
                return None
            if retry_count < MAX_RETRIES:
                time.sleep(1)  # Brief backoff before retry
                return self._call_llm_with_retry(
                    prompt,
                    retry_count + 1,
                    timings=timings,
                )

            self.stats["llm_failures"] += 1
            return None

    def generate(
        self,
        prompt: str,
        resources: List[Dict] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        Generate answer using LLM with safe fallback to knowledge base.

        Parameters:
            prompt: The prompt to send to LLM
            resources: Optional list of resources to use for fallback
        """
        if not (USE_LLM and client):
            logger.info("LLM unavailable — using knowledge base fallback")
            self.stats["fallback_uses"] += 1
            self._last_generation_mode = "fallback"
            return self._generate_fallback_answer(prompt, resources)

        if time.time() < LLM_COOLDOWN_UNTIL:
            logger.info("LLM cooldown active — using knowledge base fallback")
            self.stats["fallback_uses"] += 1
            self._last_generation_mode = "fallback"
            return self._generate_fallback_answer(prompt, resources)

        if _rag_scope_retry_after_seconds() > 0:
            logger.info("Gemini shared scope cooldown active â€” using knowledge base fallback")
            self.stats["fallback_uses"] += 1
            self._last_generation_mode = "fallback"
            return self._generate_fallback_answer(prompt, resources)

        # Call LLM
        answer = self._call_llm_with_retry(prompt, timings=timings)

        if answer:
            self.stats["successful_answers"] += 1
            self._last_generation_mode = "llm"
            return answer

        # Fallback if LLM fails
        logger.warning("LLM generation failed — using knowledge base fallback")
        self.stats["fallback_uses"] += 1
        self._last_generation_mode = "fallback"
        return self._generate_fallback_answer(prompt, resources)

    def _generate_fallback_answer(
        self, prompt: str, resources: List[Dict] = None
    ) -> str:
        """
        Generate focused answer using knowledge base when LLM unavailable or failed.
        Creates targeted answer that addresses the specific question, not just listing documents.
        Khi Gemini API quota hết, vẫn trả về câu trả lời từ knowledge base.
        """
        # Extract question from prompt to focus the answer
        question_text = ""
        q_start = prompt.find("CÂU HỎI CỦA NGƯỜI HỌC:")
        if q_start < 0:
            q_start = prompt.find("CÂU HỎI:")
        if q_start > 0:
            q_end = prompt.find("\n\nCÂU TRẢ LỜI", q_start)
            if q_end < 0:
                q_end = prompt.find("\n\nANSWER", q_start)
            if q_end > 0:
                raw_question = prompt[q_start:q_end].strip()
                question_text = (
                    raw_question.replace("CÂU HỎI CỦA NGƯỜI HỌC:", "")
                    .replace("CÂU HỎI:", "")
                    .strip()
                )

        # Priority 1: If have resources, use them to build focused answer
        if resources:
            logger.info(
                f"Using fallback: generating targeted answer from {len(resources)} resources"
            )

            definition_intent = _is_definition_question(question_text)
            main_terms = _extract_main_terms(question_text)

            # Extract best snippets and rank by lexical overlap with the question
            resource_snippets = []
            for r in resources[:8]:  # Use up to 8 resources
                snippet = r.get("snippet", "").strip()
                title = r.get("title", "Unknown").strip()
                score = r.get("score", 0)

                if snippet:
                    # Clean up snippet
                    snippet = " ".join(snippet.split())
                    overlap = _keyword_overlap_score(question_text, snippet)
                    def_sentence = ""
                    def_hit = 0
                    if definition_intent and main_terms:
                        def_sentence = _find_definition_sentence(main_terms, snippet)
                        def_hit = 1 if def_sentence else 0
                    resource_snippets.append(
                        {
                            "title": title,
                            "content": snippet,
                            "score": score,
                            "overlap": overlap,
                            "def_hit": def_hit,
                            "def_sentence": def_sentence,
                        }
                    )

            if resource_snippets:
                if (
                    definition_intent
                    and max(r.get("def_hit", 0) for r in resource_snippets) == 0
                ):
                    fallback_resources = self._get_default_resources(
                        question_text, None
                    )
                    if fallback_resources:
                        resource_snippets = []
                        for r in fallback_resources:
                            snippet = (r.get("snippet") or "").strip()
                            title = r.get("title", "Unknown").strip()
                            score = r.get("score", 0)
                            if snippet:
                                snippet = " ".join(snippet.split())
                                overlap = _keyword_overlap_score(question_text, snippet)
                                def_sentence = ""
                                def_hit = 0
                                if definition_intent and main_terms:
                                    def_sentence = _find_definition_sentence(
                                        main_terms, snippet
                                    )
                                    def_hit = 1 if def_sentence else 0
                                resource_snippets.append(
                                    {
                                        "title": title,
                                        "content": snippet,
                                        "score": score,
                                        "overlap": overlap,
                                        "def_hit": def_hit,
                                        "def_sentence": def_sentence,
                                    }
                                )

                # Prefer snippets that share keywords with the question
                resource_snippets.sort(
                    key=lambda x: (
                        x.get("def_hit", 0),
                        x.get("overlap", 0),
                        x.get("score", 0),
                    ),
                    reverse=True,
                )

                if resource_snippets[0].get("overlap", 0) == 0:
                    return "Xin lỗi, tài liệu hiện có chưa chứa thông tin khớp với câu hỏi này."

                answer_parts = []

                # Build focused answer
                if question_text:
                    answer_parts.append("## Trả lời\n\n")

                # Main content from best snippet
                best_content = resource_snippets[0]["content"]
                if definition_intent and resource_snippets[0].get("def_sentence"):
                    best_content = resource_snippets[0]["def_sentence"]
                if len(best_content) > 900:
                    best_content = best_content[:900] + "..."

                answer_parts.append(f"{best_content}\n")

                # Add supporting info with sources
                if len(resource_snippets) > 1:
                    answer_parts.append("\n### Thông tin bổ sung\n\n")
                    for item in resource_snippets[1:5]:  # Up to 4 more sources
                        excerpt = item["content"][:250]
                        if len(item["content"]) > 250:
                            excerpt += "..."
                        # Clean up title
                        source_title = item["title"].split(" - ")[0].strip()
                        answer_parts.append(f"- **{source_title}**: {excerpt}\n")

                answer = "".join(answer_parts)

                # Truncate if too long
                if len(answer) > 2500:
                    answer = answer[:2500] + "\n\n*(Nội dung được cắt ngắn)*"

                return answer

        # Fallback 2: Extract context from prompt
        context_start = prompt.find("TÀI LIỆU HỌC TẬP:")
        if context_start > 0:
            context_end = prompt.find("====================\n\n", context_start)
            if context_end > 0:
                context = prompt[context_start + 23 : context_end].strip()
                if context and len(context) > 50:
                    answer = f"## Dựa trên tài liệu\n\n{context}"
                    if len(answer) > 2500:
                        answer = answer[:2500] + "\n\n*(Nội dung được cắt ngắn)*"
                    return answer

        # Fallback 3: English context
        context_start = prompt.find("LEARNING MATERIALS:")
        if context_start > 0:
            context_end = prompt.find("====================", context_start)
            if context_end > 0:
                context = prompt[context_start + 19 : context_end].strip()
                if context and len(context) > 50:
                    return f"## Based on Learning Materials\n\n{context}"

        # Fallback 4: Knowledge base from question
        question_start = prompt.find("CÂU HỎI CỦA NGƯỜI HỌC:")
        if question_start < 0:
            question_start = prompt.find("QUESTION:")

        if question_start > 0:
            q_section = prompt[question_start:].split("\n")[0:2]
            question = (
                " ".join(q_section)
                .replace("CÂU HỎI CỦA NGƯỜI HỌC:", "")
                .replace("QUESTION:", "")
                .strip()
                .lower()
            )

            # Rich knowledge base - Vietnamese, Python-focused
            kb = {
                "python là gì": """Python là một ngôn ngữ lập trình bậc cao, được tạo ra năm 1991 bởi Guido van Rossum. 

Đặc điểm nổi bật của Python:
- **Dễ học, dễ đọc**: Cú pháp rõ ràng, giống ngôn ngữ tự nhiên
- **Đa năng**: Web development, data science, AI, automation, scripting
- **Mạnh mẽ**: Thư viện phong phú (Django, NumPy, Pandas, TensorFlow...)
- **Cộng động lớn**: Hỗ trợ tốt, tài liệu phong phú
- **Miễn phí, mã nguồn mở**: Có thể sử dụng cho mục đích thương mại

Ứng dụng thực tế:
- Web: Django, Flask
- Data Science: Pandas, NumPy, SciPy
- Machine Learning: TensorFlow, PyTorch, Scikit-learn
- Automation: Script các tác vụ lặp lại
- Game development: Pygame

Tại sao học Python?
1. Cú pháp dễ hiểu → tập trung vào logic, không vào syntax
2. Cộng động lớn → dễ tìm hỗ trợ
3. Cơ hội việc làm cao
4. Nền tảng tốt để học lập trình""",
                "python": """Python là một ngôn ngữ lập trình bậc cao, được biết đến vì tính đơn giản, linh hoạt và mạnh mẽ. 

Được sử dụng rộng rãi cho:
- Phát triển web (Django, Flask)
- Phân tích dữ liệu (Pandas, NumPy)
- Machine learning (TensorFlow, PyTorch)
- Tự động hóa (scripts, task automation)
- Scientific computing
- Hệ thống tư vấn

Python nổi tiếng vì cú pháp đơn giản và làm việc lần đầu rất dễ.""",
                "list": "Trong Python, list (danh sách) là một tập hợp có thứ tự, có thể thay đổi được. Bạn có thể tạo list bằng dấu ngoặc vuông: my_list = [1, 2, 3]. List hỗ trợ indexing, slicing, và các phương thức như append(), remove(), sort().",
                "dict": "Dictionary (từ điển) trong Python là một tập hợp các cặp key-value. Bạn tạo dictionary bằng dấu ngoặc nhọn: my_dict = {'key': 'value'}. Truy cập giá trị bằng key: my_dict['key'].",
                "function": "Function (hàm) là một khối mã có thể tái sử dụng để thực hiện một nhiệm vụ cụ thể. Trong Python, bạn định nghĩa function bằng từ khóa 'def': def my_function(): pass. Function có thể nhận tham số và trả về giá trị.",
                "loop": "Loop (vòng lặp) cho phép bạn lặp lại một khối mã nhiều lần. Python có 'for' loop để lặp qua các chuỗi và 'while' loop để lặp có điều kiện.",
                "class": "Class (lớp) là một bản thiết kế để tạo các object (đối tượng). Nó định nghĩa các thuộc tính (properties) và hành vi (methods). Class là nền tảng của lập trình hướng đối tượng (OOP) trong Python.",
            }

            # Try exact match first
            if question in kb:
                return kb[question]

            # Try partial match
            for key, answer in kb.items():
                if key in question:
                    return answer

            # Generic fallback
            return (
                "Tôi rất tiếc vì AI service hiện không khả dụng (API quota exceeded). "
                "Tuy nhiên, đây là những thông tin cơ bản bạn có thể tham khảo:\n\n"
                "1. Kiểm tra phần 'Lộ trình Học tập' để tìm các khái niệm liên quan\n"
                "2. Duyệt qua 'Tài nguyên' để tìm hướng dẫn chi tiết\n"
                "3. Truy cập tài liệu chính thức Python: https://docs.python.org\n\n"
                "⏰ API sẽ reset vào ngày hôm sau. Vui lòng thử lại sau."
            )

        return (
            "Tôi gặp khó khăn trong việc trích xuất thông tin. "
            "Vui lòng thử lại hoặc tham khảo phần tài liệu học tập."
        )

    # =========================
    # 5. DIRECT ANSWER FROM CONTEXT
    # =========================
    def _can_answer_from_context(self, resources: List[Dict]) -> bool:
        """
        Kiểm tra xem có thể trả lời trực tiếp từ context hay không.

        Điều kiện (phải thỏa TẤT CẢ):
        1. Phải có tài liệu THỰC từ database (không phải fallback)
        2. Có ít nhất MIN_HIGH_QUALITY_RESOURCES (2) tài liệu với score >= DIRECT_ANSWER_THRESHOLD (0.80)

        Threshold cao (0.80) đảm bảo câu trả lời sẽ TẬP TRUNG vào câu hỏi, không lạc đi.

        Returns:
            bool: True nếu có thể trả lời trực tiếp từ context
        """
        if not resources:
            return False

        # ⚠️  CHỈ xét tài liệu THỰC từ database, KHÔNG phải fallback
        real_resources = [r for r in resources if r.get("is_real_resource", False)]

        if not real_resources:
            logger.info("❌ No real resources from database - must use AI")
            return False

        # Đếm số tài liệu chất lượng cao (CHỈ trong real resources)
        # ⭐ Threshold cao (0.80) = confidence cao = trả lời chính xác + tập trung
        high_quality = [
            r for r in real_resources if r.get("score", 0) >= DIRECT_ANSWER_THRESHOLD
        ]

        # Phải có ít nhất 2 tài liệu chất lượng cao để trả lời chính xác
        can_answer = len(high_quality) >= MIN_HIGH_QUALITY_RESOURCES

        if can_answer:
            avg_score = sum(r.get("score", 0) for r in high_quality) / len(high_quality)
            logger.info(
                f"✅ Can answer from context: {len(high_quality)} high-quality resources "
                f"(avg score: {avg_score:.2f}, threshold: {DIRECT_ANSWER_THRESHOLD})"
            )
        else:
            logger.info(
                f"❌ Cannot answer from context: only {len(high_quality)} high-quality resources "
                f"(need >= {MIN_HIGH_QUALITY_RESOURCES} with score >= {DIRECT_ANSWER_THRESHOLD}). "
                f"Will use AI for accurate answer."
            )

        return can_answer

    def _generate_direct_answer(self, question: str, resources: List[Dict]) -> str:
        """
        Generate focused answer directly from resources that best address the question.
        Creates a coherent synthesis, not just document listing.

        Returns:
            str: Markdown-formatted answer synthesized from best resources
        """
        if not resources:
            return "Xin lỗi, tôi không tìm thấy thông tin liên quan trong tài liệu học tập."

        # Sort by question overlap, then relevance score
        definition_intent = _is_definition_question(question)
        main_terms = _extract_main_terms(question)

        def _rank_key(resource: Dict) -> tuple:
            snippet = (resource.get("snippet") or "").strip()
            overlap = _keyword_overlap_score(question, snippet)
            def_hit = 0
            if definition_intent and main_terms:
                def_hit = 1 if _find_definition_sentence(main_terms, snippet) else 0
            return (def_hit, overlap, resource.get("score", 0))

        sorted_resources = sorted(resources, key=_rank_key, reverse=True)
        top_resources = sorted_resources[:5]

        if (
            not top_resources
            or _keyword_overlap_score(question, top_resources[0].get("snippet", ""))
            == 0
        ):
            return "Xin lỗi, tài liệu hiện có chưa chứa thông tin khớp với câu hỏi này."

        answer_parts = []

        # Main answer content from best resource
        best = top_resources[0]
        best_snippet = best.get("snippet", "").strip()
        if best_snippet:
            # Clean and format main content
            best_snippet = " ".join(best_snippet.split())  # Remove excessive whitespace
            if definition_intent and main_terms:
                def_sentence = _find_definition_sentence(main_terms, best_snippet)
                if not def_sentence:
                    return "Xin lỗi, tài liệu hiện có chưa chứa thông tin khớp với câu hỏi này."
                best_snippet = def_sentence
            if len(best_snippet) > 1000:
                best_snippet = best_snippet[:1000] + "..."
            answer_parts.append(f"## Trả lời\n\n{best_snippet}\n")

        # Add supporting information from other resources
        if len(top_resources) > 1:
            answer_parts.append("\n### Thông tin thêm\n\n")
            for resource in top_resources[1:]:
                snippet = resource.get("snippet", "").strip()
                title = resource.get("title", "Unknown").strip()
                if snippet:
                    # Extract first 200 chars as supplementary excerpt
                    excerpt = " ".join(snippet.split())  # Clean whitespace
                    if len(excerpt) > 250:
                        excerpt = excerpt[:250] + "..."
                    source_title = title.split(" - ")[0].strip()
                    answer_parts.append(f"- **{source_title}**: {excerpt}\n")

        # Add sources
        answer_parts.append("\n### 📚 Nguồn tham khảo\n\n")
        for idx, resource in enumerate(top_resources, 1):
            title = resource.get("title", "Unknown")
            score = resource.get("score", 0)
            answer_parts.append(f"{idx}. {title} (độ liên quan: {score:.0%})\n")

        return "".join(answer_parts)

    def _format_answer_beautifully(self, raw_text: str, resources: List[Dict]) -> str:
        """
        Format raw answer text into beautifully structured Markdown.
        Improves readability and visual presentation.
        """
        if not raw_text:
            return "Xin lỗi, không thể tạo câu trả lời."

        # Clean up text
        text = raw_text.strip()

        # Split into sentences for better formatting
        lines = text.split("\n")

        # Build formatted answer with better structure
        formatted_parts = []

        # Add introduction
        formatted_parts.append("## 📚 Câu Trả Lời\n")

        # Process content with better formatting
        current_section = []
        for line in lines:
            line = line.strip()
            if line and len(line) > 10:
                current_section.append(line)

        # Combine sections
        if current_section:
            formatted_parts.append("\n".join(current_section))

        # Add sources section
        if resources:
            formatted_parts.append("\n\n## 📖 Nguồn Tham Khảo\n")
            sorted_resources = sorted(
                resources, key=lambda x: x.get("score", 0), reverse=True
            )[:3]

            for idx, resource in enumerate(sorted_resources, 1):
                title = resource.get("title", "Unknown")
                score = resource.get("score", 0)
                formatted_parts.append(f"- **{title}** - Độ liên quan: {score:.0%}")

        return "\n".join(formatted_parts)

    def _build_fallback_context(self, question: str, goal: Optional[str]) -> str:
        """
        Xây dựng context từ fallback knowledge base khi không có tài liệu thực.
        Context này sẽ được dùng bởi AI để tạo câu trả lời tốt hơn.

        Returns:
            str: Context cho AI
        """
        fallback_resources = self._get_default_resources(goal, None)

        if fallback_resources:
            # Đánh dấu là fallback
            for r in fallback_resources:
                r["is_real_resource"] = False

            # Build context từ fallback resources - rõ ràng là bổ sung
            context_parts = []
            context_parts.append(
                "[Lưu ý: Hệ thống không tìm thấy tài liệu cụ thể trong cơ sở dữ liệu cho câu hỏi này]\n[Dưới đây là kiến thức bổ sung từ knowledge base có sẵn]\n\n"
            )

            for idx, r in enumerate(fallback_resources, 1):
                snippet = r.get("snippet", "")
                title = r.get("title", "Unknown")
                context_parts.append(f"[Nguồn {idx}: {title}]\n{snippet}\n\n")

            return "".join(context_parts)

        return "Không có thông tin cụ thể trong hệ thống."

    # =========================
    # 6. RUN FULL PIPELINE
    # =========================
    def run(
        self,
        question: str,
        goal: str,
        level: str,
        completed: Optional[List[str]] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        Execute full QA-RAG pipeline.
        """
        start_time = perf_counter()
        self.stats["total_runs"] += 1

        logger.info(
            f"RAG pipeline start: question={question[:60]}..., goal={goal}, level={level}"
        )

        # Validate
        if not _validate_input(question, goal):
            return {
                "question": question,
                "answer": "Invalid input. Please provide a valid question and learning goal.",
                "sources": [],
                "error": "validation_failed",
            }

        try:
            # 1. Retrieve
            resources = self.retrieve_context(
                query=question,
                goal=goal,
                level=level,
                k=RETRIEVAL_K,
                timings=timings,
            )

            # 2. Kiểm tra xem có thể trả lời trực tiếp từ context không
            answer_text = None
            answer_method = "unknown"

            if self._can_answer_from_context(resources):
                # ✅ Trả lời trực tiếp từ context
                logger.info(
                    "📚 Answering directly from learning materials (no AI needed)"
                )
                answer_text = self._generate_direct_answer(question, resources)
                answer_method = "direct_from_context"
                self.stats["direct_answers"] += 1
            else:
                # ❌ Không đủ chất lượng hoặc không có tài liệu, PHẢI dùng AI để trả lời chính xác
                can_use_llm = USE_LLM and client and time.time() >= LLM_COOLDOWN_UNTIL
                if can_use_llm:
                    logger.info(
                        f"🤖 Using AI for accurate answer: "
                        f"resources insufficient (need >= {MIN_HIGH_QUALITY_RESOURCES} "
                        f"with score >= {DIRECT_ANSWER_THRESHOLD})"
                    )
                else:
                    logger.info(
                        "LLM unavailable or cooldown active — using retrieval fallback"
                    )

                # 3. Build context (có thể rỗng nếu không có tài liệu)
                if resources:
                    context = self.build_context(resources)
                else:
                    # Không có tài liệu, dùng fallback context
                    context = self._build_fallback_context(question, goal)

                # 4. Build prompt with formatting guidance
                prompt = self.build_prompt(question, context)

                # 5. Generate answer with AI (pass resources for fallback)
                answer_text = self.generate(prompt, resources, timings=timings)
                if self._last_generation_mode == "fallback":
                    answer_method = "retrieval_fallback"
                else:
                    answer_method = "ai_generated"
                    self.stats["ai_answers"] += 1

            # 6. Return structured response
            elapsed_ms = (perf_counter() - start_time) * 1000
            self.stats["total_latency_ms"] += elapsed_ms
            add_timing(timings, "rag_total_ms", elapsed_ms / 1000.0)

            logger.info(
                f"RAG pipeline complete: "
                f"method={answer_method}, "
                f"resources={len(resources)}, "
                f"answer_len={len(answer_text)}, "
                f"latency={elapsed_ms:.1f}ms"
            )

            return {
                "success": True,
                "question": question,
                "answer": answer_text,
                "answer_method": answer_method,  # Thêm thông tin về phương pháp trả lời
                "sources": [
                    {
                        "resource_id": r.get("resource_id"),
                        "title": r.get("title"),
                        "score": round(r.get("score", 0), 3),
                        "source": r.get("source"),
                    }
                    for r in resources
                ],
                "latency_ms": round(elapsed_ms, 1),
                "timings": dict(timings or {}),
            }

        except Exception as e:
            logger.exception(f"RAG pipeline error: {e}")
            return {
                "success": False,
                "question": question,
                "answer": "An error occurred while processing your question. Please try again.",
                "sources": [],
                "error": str(e),
            }

    @staticmethod
    def _time_now() -> float:
        return time.time()

    def build_context(self, resources: List[Dict]) -> str:
        return build_ai_tutor_context(
            self,
            resources=resources,
            max_context_chars=MAX_CONTEXT_CHARS,
            truncate_to_sentence=_truncate_to_sentence,
            logger=logger,
        )

    def build_prompt(self, question: str, context: str) -> str:
        return build_ai_tutor_prompt(
            self,
            question=question,
            context=context,
            max_prompt_chars=MAX_PROMPT_CHARS,
            truncate_to_sentence=_truncate_to_sentence,
            logger=logger,
        )

    def generate(
        self,
        prompt: str,
        resources: List[Dict] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> str:
        return generate_ai_tutor_answer(
            self,
            prompt=prompt,
            resources=resources,
            use_llm=USE_LLM,
            client=client,
            llm_cooldown_until=LLM_COOLDOWN_UNTIL,
            retry_after_seconds=_rag_scope_retry_after_seconds(),
            logger=logger,
            timings=timings,
        )

    def _generate_fallback_answer(
        self, prompt: str, resources: List[Dict] = None
    ) -> str:
        return generate_ai_tutor_fallback_answer(
            self,
            prompt=prompt,
            resources=resources,
            logger=logger,
            is_definition_question=_is_definition_question,
            extract_main_terms=_extract_main_terms,
            keyword_overlap_score=_keyword_overlap_score,
            find_definition_sentence=_find_definition_sentence,
        )

    def _can_answer_from_context(self, resources: List[Dict]) -> bool:
        return can_answer_ai_tutor_from_context(
            resources=resources,
            logger=logger,
            direct_answer_threshold=DIRECT_ANSWER_THRESHOLD,
            min_high_quality_resources=MIN_HIGH_QUALITY_RESOURCES,
        )

    def _generate_direct_answer(self, question: str, resources: List[Dict]) -> str:
        return generate_ai_tutor_direct_answer(
            question=question,
            resources=resources,
            is_definition_question=_is_definition_question,
            extract_main_terms=_extract_main_terms,
            keyword_overlap_score=_keyword_overlap_score,
            find_definition_sentence=_find_definition_sentence,
        )

    def _format_answer_beautifully(self, raw_text: str, resources: List[Dict]) -> str:
        return format_ai_tutor_answer(raw_text, resources)

    def _build_fallback_context(self, question: str, goal: Optional[str]) -> str:
        return build_ai_tutor_fallback_context(self, question, goal)

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
            "direct_answers": self.stats["direct_answers"],
            "ai_answers": self.stats["ai_answers"],
            "llm_failures": self.stats["llm_failures"],
            "retrieval_failures": self.stats["retrieval_failures"],
            "fallback_uses": self.stats["fallback_uses"],
            "avg_latency_ms": round(avg_latency, 1),
            "total_latency_ms": round(self.stats["total_latency_ms"], 1),
        }
