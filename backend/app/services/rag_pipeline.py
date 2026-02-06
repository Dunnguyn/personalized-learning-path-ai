from typing import List, Dict, Optional
import os
import logging
import re

from backend.app.services.embedding_service import semantic_search

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# LLM CONFIG (Gemini)
# =========================
USE_LLM = True
client = None

PRIMARY_MODEL = "models/gemini-2.5-flash"
MAX_CONTEXT_CHARS = 2000


try:
    from google import genai

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=GEMINI_API_KEY)

except Exception as e:
    logger.warning("❌ Gemini init error: %s", e)
    USE_LLM = False
    client = None


def _truncate_to_sentence(text: str, max_chars: int) -> str:
    """
    Truncate text to the nearest sentence boundary without exceeding max_chars.
    Fallback: if no sentence boundary found, cut to max_chars.
    """
    if len(text) <= max_chars:
        return text

    # look for sentence enders before the cutoff
    cutoff = text[:max_chars]
    # find the last occurrence of a sentence terminator followed by space/newline
    match = re.search(r'(.+?)([.!?])(?:\s|$)', cutoff[::-1])
    if match:
        # reversed match logic is complex; instead search forwards for last terminator
        last_idx = max(
            cutoff.rfind(". "),
            cutoff.rfind("? "),
            cutoff.rfind("! "),
            cutoff.rfind(".\n"),
            cutoff.rfind("?\n"),
            cutoff.rfind("!\n"),
            cutoff.rfind("."),
            cutoff.rfind("?"),
            cutoff.rfind("!")
        )
        if last_idx > 0:
            return cutoff[: last_idx + 1].strip()
    # fallback hard cut
    return cutoff.strip()


class RAGPipeline:
    """
    Retrieval-Augmented Generation (QA-RAG)

    Pipeline:
        Question → Retrieval → Context → Prompt → LLM → Answer
    """

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
        Semantic retrieval with optional personalization
        """
        return semantic_search(
            query=query,
            k=k,
            topic=goal,
            level=level
        )

    # =========================
    # 2. BUILD CONTEXT
    # =========================
    def build_context(self, resources: List[Dict]) -> str:
        """
        Build limited-length context from retrieved resources.
        Try to avoid cutting mid-sentence.
        """
        if not resources:
            return "No learning materials found."

        blocks: List[str] = []
        total_chars = 0

        for r in resources:
            title = r.get("title", "unknown")
            snippet = r.get("snippet", "") or ""
            block = f"[Source: {title}]\n{snippet}"

            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining <= 0:
                break

            if len(block) > remaining:
                truncated = _truncate_to_sentence(block, remaining)
                if truncated:
                    blocks.append(truncated)
                    total_chars += len(truncated)
                # reached limit
                break
            else:
                blocks.append(block)
                total_chars += len(block)

        return "\n\n".join(blocks)

    # =========================
    # 3. BUILD PROMPT
    # =========================
    def build_prompt(self, question: str, context: str) -> str:
        """
        RAG prompt to reduce hallucination
        """
        prompt = f"""
You are an AI tutor for beginner learners.

RULES:
- Use ONLY the learning materials below.
- Do NOT use outside knowledge.
- If the answer is not found, say exactly:
  "I cannot find the answer in the provided learning materials."

Learning materials:
--------------------
{context}
--------------------

Question:
{question}

Answer clearly and simply.
"""
        return prompt.strip()

    # =========================
    # 4. GENERATE ANSWER
    # =========================
    def _extract_text_from_response(self, response) -> Optional[str]:
        """
        Attempt several common shapes of gen AI SDK responses to extract text.
        Returns None if no text found.
        """
        if response is None:
            return None

        # Common possibilities:
        # - response.text
        # - response.output_text
        # - response.output[0].content[0].text
        # - response.candidates[0].content[0].text
        # - response.choices[0].message.content
        try:
            # direct text
            if hasattr(response, "text") and isinstance(response.text, str):
                return response.text
            if hasattr(response, "output_text") and isinstance(response.output_text, str):
                return response.output_text
            # nested patterns
            out = getattr(response, "output", None)
            if out:
                # list-like
                if isinstance(out, (list, tuple)) and len(out) > 0:
                    first = out[0]
                    content = getattr(first, "content", None) or first.get("content") if isinstance(first, dict) else None
                    if content:
                        if isinstance(content, (list, tuple)) and len(content) > 0:
                            piece = content[0]
                            text = getattr(piece, "text", None) or piece.get("text") if isinstance(piece, dict) else None
                            if isinstance(text, str):
                                return text
            # candidates pattern
            cand = getattr(response, "candidates", None) or response.get("candidates") if isinstance(response, dict) else None
            if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                first = cand[0]
                content = first.get("content") if isinstance(first, dict) else getattr(first, "content", None)
                if content and isinstance(content, (list, tuple)) and len(content) > 0:
                    piece = content[0]
                    text = piece.get("text") if isinstance(piece, dict) else getattr(piece, "text", None)
                    if isinstance(text, str):
                        return text
            # choices pattern (chat-like)
            choices = getattr(response, "choices", None) or response.get("choices") if isinstance(response, dict) else None
            if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
                first = choices[0]
                message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
                if message:
                    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
                    if isinstance(content, str):
                        return content
                    # sometimes content is list
                    if isinstance(content, (list, tuple)) and len(content) > 0:
                        piece = content[0]
                        if isinstance(piece, str):
                            return piece
        except Exception as e:
            logger.debug("Error extracting text from response: %s", e)
        return None

    def generate(self, prompt: str) -> str:
        """
        Generate answer using Gemini with safe fallback.
        Tries multiple call shapes to be robust across SDK versions.
        """
        if not (USE_LLM and client):
            # provide a helpful fallback answer synthesized from the retrieved context
            return "LLM is unavailable. " \
                   "Answer (based on retrieved materials):\n\n" + prompt.split("Learning materials:")[-1].strip()

        try:
            # Try first method used in older examples
            try:
                response = client.models.generate_content(
                    model=PRIMARY_MODEL,
                    contents=prompt
                )
            except Exception:
                # try the "generate" method
                try:
                    response = client.generate(
                        model=PRIMARY_MODEL,
                        prompt=prompt
                    )
                except Exception:
                    # try responses.create (another common pattern)
                    response = client.responses.create(
                        model=PRIMARY_MODEL,
                        input=prompt
                    )

            text = self._extract_text_from_response(response)
            if text:
                return text.strip()

            # Last resort: if no extractable text, log and return friendly message
            logger.warning("Gemini response had no extractable text; returning fallback.")
            return "LLM responded but no text could be extracted. Answer (based on retrieved materials):\n\n" + prompt.split("Learning materials:")[-1].strip()

        except Exception as e:
            logger.exception("⚠️ Gemini error during generation: %s", e)
            return "LLM is temporarily unavailable. Please try again later."

    # =========================
    # 5. RUN PIPELINE
    # =========================
    def run(
        self,
        question: str,
        goal: str,
        level: str,
        completed: List[str]
    ) -> Dict:
        """
        Execute full QA-RAG pipeline
        """

        # 1. Retrieve
        resources = self.retrieve_context(
            query=question,
            goal=goal,
            level=level
        )

        # 2. Build context
        context = self.build_context(resources)

        # 3. Build prompt
        prompt = self.build_prompt(question, context)

        # 4. Generate answer
        answer_text = self.generate(prompt)

        # 5. Structured response
        return {
            "question": question,
            "answer": answer_text,
            "sources": [
                {
                    "resource_id": r.get("resource_id"),
                    "title": r.get("title"),
                    "score": r.get("score"),
                    "source": r.get("source")
                }
                for r in resources
            ]
        }