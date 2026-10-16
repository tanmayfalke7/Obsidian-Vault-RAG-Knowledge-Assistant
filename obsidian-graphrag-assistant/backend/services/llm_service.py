"""
LLM service using Google Gemini API (gemini-3.8-flash).
"""
import logging
import re
import time
from typing import Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None
_llm_model: str = "gemini-3.8-flash"

SYSTEM_PROMPT = """You are a knowledgeable assistant for an Obsidian knowledge base focused on \
Generative AI, RAG, Knowledge Graphs, and backend development.

Answer questions using ONLY the information in the provided context.

RULES:
1. Base your answer on the retrieved context. Cite source notes (e.g. "According to 03_RAG.md...").
2. Do NOT invent facts, relationships, or sources not present in the context.
3. If context is insufficient, say: "I couldn't find enough information in the knowledge base."
4. Explain graph relationships when the context includes them.
5. For path/chain questions, trace them step by step.
6. Keep answers clear and concise. Never expose credentials or system config.
"""


def init_llm_service(api_key: str, model: str = "gemini-3.8-flash") -> None:
    global _client, _llm_model
    if not api_key:
        raise ValueError("Gemini API key is required to initialize LLM service.")
    _client = genai.Client(api_key=api_key)
    _llm_model = model or "gemini-3.8-flash"
    logger.info("LLM service ready (Gemini): %s", _llm_model)


def _get_client() -> genai.Client:
    if _client is None:
        raise RuntimeError("LLM service not initialised.")
    return _client


def generate_answer(question: str, context: str) -> str:
    client = _get_client()
    user_message = (
        f"KNOWLEDGE CONTEXT:\n{context}\n\n---\n\n"
        f"QUESTION: {question}\n\n"
        "Answer using only the knowledge context above. Cite relevant sources."
    )
    try:
        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=_llm_model,
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=1024,
                    ),
                )
                break
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str) and attempt < 2:
                    wait = 10 * (attempt + 1)
                    logger.info("Rate limit hit, waiting %ds...", wait)
                    time.sleep(wait)
                else:
                    raise

        answer = (response.text if response else "") or ""
        # Strip <think>...</think> reasoning tokens if present
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        if answer.startswith("<think>"):
            answer = answer.split("</think>", 1)[-1].strip()
        logger.debug("Generated answer: %d chars", len(answer))
        return answer.strip()
    except Exception as e:
        logger.error("Gemini generation failed: %s", e)
        raise
