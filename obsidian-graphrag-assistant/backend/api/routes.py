"""
FastAPI route definitions.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Path as FPath

from backend.models.schemas import (
    QueryRequest, QueryResponse, SourceReference, GraphRelationship,
    IngestRequest, IngestResponse,
    HealthResponse, StatsResponse,
    GraphExploreResponse, GraphNeighbour,
    NoteInfo,
)
from backend.services import rag_service, graph_service, ingestion_service
from backend.db.neo4j_client import verify_connectivity
from backend.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check():
    """Check Neo4j connectivity and Groq configuration."""
    neo4j_ok = verify_connectivity()
    groq_ok = bool(settings.groq_api_key)
    return HealthResponse(
        status="ok" if (neo4j_ok and groq_ok) else "degraded",
        neo4j="connected" if neo4j_ok else "disconnected",
        gemini="configured" if groq_ok else "not_configured",
    )


# ── Query ─────────────────────────────────────────────────────────────────────

@router.post("/api/query", response_model=QueryResponse, tags=["rag"])
def query(request: QueryRequest):
    """
    Ask a question and receive a GraphRAG-powered answer.

    Pipeline: embed → vector search → graph traversal → LLM generation.
    """
    try:
        result = rag_service.ask(
            question=request.question,
            user_id="system",  # Legacy endpoint uses system scope
            top_k=request.top_k,
        )
    except Exception as e:
        logger.error("Query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Query processing failed.") from e

    sources = [
        SourceReference(
            title=s.get("title", ""),
            filename=s.get("filename", ""),
            score=s.get("score"),
        )
        for s in result.sources
    ]
    relationships = [
        GraphRelationship(
            source=r.get("source", ""),
            relationship=r.get("relationship", ""),
            target=r.get("target", ""),
        )
        for r in result.relationships
    ]

    return QueryResponse(
        answer=result.answer,
        sources=sources,
        relationships=relationships,
        chunks_used=result.chunks_used,
    )


# ── Ingest ────────────────────────────────────────────────────────────────────

@router.post("/api/ingest", response_model=IngestResponse, tags=["ingestion"])
def ingest(request: IngestRequest = None):
    """
    Trigger vault ingestion.

    Reads markdown files from data/vault, creates graph nodes, generates
    embeddings, and populates the vector index.
    """
    if request is None:
        request = IngestRequest()

    project_root = Path(__file__).resolve().parents[2]
    vault_path = (
        Path(request.vault_path).expanduser()
        if request.vault_path
        else settings.vault_path
    ).resolve()
    try:
        vault_path.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Vault path must stay inside the project directory.")

    if not vault_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Vault path does not exist.",
        )

    try:
        stats = ingestion_service.run_ingestion(vault_path, user_id="system", reset=request.reset)
    except Exception as e:
        logger.error("Ingestion failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ingestion failed.") from e

    return IngestResponse(
        success=len(stats.errors) == 0,
        notes_processed=stats.notes_processed,
        chunks_created=stats.chunks_created,
        concepts_created=stats.concepts_created,
        relationships_created=stats.relationships_created,
        embeddings_generated=stats.embeddings_generated,
        errors=stats.errors,
    )


# ── Sources ───────────────────────────────────────────────────────────────────

@router.get("/api/sources", response_model=list[NoteInfo], tags=["knowledge-base"])
def list_sources():
    """List all notes stored in the knowledge base."""
    try:
        notes = graph_service.get_all_notes(user_id="system")
    except Exception as e:
        logger.error("Failed to fetch sources: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch sources.") from e

    return [
        NoteInfo(
            id=n.get("id", ""),
            title=n.get("title", ""),
            filename=n.get("filename", ""),
            chunk_count=n.get("chunk_count", 0),
        )
        for n in notes
    ]


# ── Graph Explorer ────────────────────────────────────────────────────────────

@router.get(
    "/api/graph/{concept}",
    response_model=GraphExploreResponse,
    tags=["knowledge-base"],
)
def get_graph_neighbours(concept: str = FPath(..., description="Concept name")):
    """Return the 1-hop graph neighbourhood of a named concept."""
    try:
        results = graph_service.get_concept_neighbours(concept, user_id="system")
    except Exception as e:
        logger.error("Graph lookup failed for '%s': %s", concept, e)
        raise HTTPException(status_code=500, detail="Graph lookup failed.") from e

    if not results or results[0].get("concept") is None:
        return GraphExploreResponse(concept=concept, neighbours=[], found=False)

    row = results[0]
    neighbours: list[GraphNeighbour] = []

    for item in row.get("outgoing", []):
        if item.get("concept") and item.get("relationship"):
            neighbours.append(
                GraphNeighbour(
                    concept=item["concept"],
                    relationship=item["relationship"],
                    direction="outgoing",
                )
            )
    for item in row.get("incoming", []):
        if item.get("concept") and item.get("relationship"):
            neighbours.append(
                GraphNeighbour(
                    concept=item["concept"],
                    relationship=item["relationship"],
                    direction="incoming",
                )
            )

    return GraphExploreResponse(
        concept=row.get("concept", concept),
        neighbours=neighbours,
        found=True,
    )


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/api/stats", response_model=StatsResponse, tags=["system"])
def get_stats():
    """Return knowledge base statistics."""
    try:
        raw = graph_service.get_graph_stats(user_id="system")
        index_status = graph_service.get_vector_index_status(settings.vector_index_name)
    except Exception as e:
        logger.error("Stats query failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch stats.") from e

    return StatsResponse(
        notes=raw.get("notes", 0),
        chunks=raw.get("chunks", 0),
        concepts=raw.get("concepts", 0),
        relationships=raw.get("rels", 0),
        vector_index=index_status,
    )
