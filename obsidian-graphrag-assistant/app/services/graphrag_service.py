"""
Bridge between the web app and the existing GraphRAG pipeline.

This module is the ONLY place that imports from backend/.
All existing backend services are used as-is — nothing is modified.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Lazy-import so startup continues even if services not yet initialised
_services_ready = False


def ensure_services() -> None:
    """Initialise GraphRAG services if not already done."""
    global _services_ready
    if _services_ready:
        return
    from app.config import settings
    from backend.db.neo4j_client import init_driver, verify_connectivity
    from backend.services.embedding_service import init_embedding_service
    from backend.services.llm_service import init_llm_service

    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    if not verify_connectivity():
        logger.warning("Neo4j connectivity check failed during service init.")

    init_embedding_service(settings.embedding_model)
    init_llm_service(settings.groq_api_key, settings.groq_llm_model)
    _services_ready = True
    logger.info("GraphRAG services initialised.")


@dataclass
class ChatResponse:
    answer: str
    sources: list[dict]         # [{title, filename, score}]
    relationships: list[dict]   # [{source, relationship, target}]
    chunks_used: int
    error: str | None = None


def ask_graphrag(question: str, top_k: int = 5) -> ChatResponse:
    """
    Run the full GraphRAG pipeline for a user question.
    Returns ChatResponse — never raises; errors are captured in .error.
    """
    ensure_services()
    try:
        from backend.services.rag_service import ask
        result = ask(question, top_k=top_k)
        return ChatResponse(
            answer=result.answer,
            sources=result.sources,
            relationships=result.relationships,
            chunks_used=result.chunks_used,
        )
    except Exception as e:
        logger.error("GraphRAG ask() failed: %s", e, exc_info=True)
        return ChatResponse(
            answer="",
            sources=[],
            relationships=[],
            chunks_used=0,
            error=str(e),
        )


def get_graph_stats() -> dict:
    ensure_services()
    try:
        from backend.services.graph_service import get_graph_stats
        return get_graph_stats()
    except Exception as e:
        logger.warning("get_graph_stats failed: %s", e)
        return {"notes": 0, "chunks": 0, "concepts": 0, "rels": 0}


def get_concept_neighbours(concept: str) -> dict:
    ensure_services()
    try:
        from backend.services.graph_service import get_concept_neighbours
        results = get_concept_neighbours(concept)
        if not results or results[0].get("concept") is None:
            return {"concept": concept, "found": False, "outgoing": [], "incoming": []}
        row = results[0]
        outgoing = [
            i for i in (row.get("outgoing") or [])
            if i.get("concept") and i.get("relationship")
        ]
        incoming = [
            i for i in (row.get("incoming") or [])
            if i.get("concept") and i.get("relationship")
        ]
        return {
            "concept": row.get("concept", concept),
            "found": True,
            "outgoing": outgoing,
            "incoming": incoming,
        }
    except Exception as e:
        logger.warning("get_concept_neighbours failed: %s", e)
        return {"concept": concept, "found": False, "outgoing": [], "incoming": []}


def ingest_user_documents(vault_path: str, reset: bool = False) -> dict:
    """Trigger ingestion of a user's vault directory."""
    ensure_services()
    from pathlib import Path
    try:
        from backend.services.ingestion_service import run_ingestion
        stats = run_ingestion(Path(vault_path), reset=reset)
        return {
            "success": len(stats.errors) == 0,
            "notes": stats.notes_processed,
            "chunks": stats.chunks_created,
            "embeddings": stats.embeddings_generated,
            "errors": stats.errors,
        }
    except Exception as e:
        logger.error("Ingestion failed: %s", e)
        return {"success": False, "errors": [str(e)]}
