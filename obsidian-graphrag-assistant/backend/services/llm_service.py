"""
LLM service using Groq API (llama-3.3-70b-versatile).
"""
import logging
from typing import Optional
from groq import Groq

logger = logging.getLogger(__name__)

_client: Optional[Groq] = None
_llm_model: str = ""

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


def init_llm_service(api_key: str, model: str) -> None:
    global _client, _llm_model
    _client = Groq(api_key=api_key)
    _llm_model = model
    logger.info("LLM service ready: %s", model)


def _get_client() -> Groq:
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
        import time
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=_llm_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    wait = 10 * (attempt + 1)
                    logger.info("Rate limit hit, waiting %ds...", wait)
                    time.sleep(wait)
                else:
                    raise
        answer = resp.choices[0].message.content or ""
        # Strip <think>...</think> reasoning tokens (Qwen/reasoning models)
        import re
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        # Also strip if the answer starts with just a reasoning trace fragment
        if answer.startswith("<think>"):
            answer = answer.split("</think>", 1)[-1].strip()
        logger.debug("Generated answer: %d chars", len(answer))
        return answer.strip()
    except Exception as e:
        logger.error("Groq generation failed: %s", e)
        raise
