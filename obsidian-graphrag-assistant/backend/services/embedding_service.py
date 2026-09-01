"""
Embedding service using fastembed (local, no API key required).
Model: BAAI/bge-small-en-v1.5 — 384 dims, fast, accurate.
"""
import logging
from typing import Optional
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

_model: Optional[TextEmbedding] = None
_model_name: str = ""


def init_embedding_service(model_name: str) -> None:
    """Load the embedding model (downloads on first use, cached after)."""
    global _model, _model_name
    logger.info("Loading embedding model: %s", model_name)
    _model = TextEmbedding(model_name=model_name)
    _model_name = model_name
    logger.info("Embedding model ready: %s", model_name)


def _get_model() -> TextEmbedding:
    if _model is None:
        raise RuntimeError("Embedding service not initialised. Call init_embedding_service() first.")
    return _model


def embed_text(text: str, **kwargs) -> list[float]:
    """Embed a single text string. Returns a list of floats."""
    text = text.strip()
    if not text:
        raise ValueError("Cannot embed empty text.")
    model = _get_model()
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def embed_texts(texts: list[str], **kwargs) -> list[list[float]]:
    """Embed a list of texts. Returns list of float lists."""
    model = _get_model()
    results = []
    for text in texts:
        if not text.strip():
            results.append([])
            continue
        emb = list(model.embed([text]))[0].tolist()
        results.append(emb)
    logger.info("Generated %d embeddings.", len([r for r in results if r]))
    return results


def embed_query(question: str) -> list[float]:
    """Embed a query for similarity search."""
    return embed_text(question)
