"""
RAG routes — GraphRAG query endpoints.

Security contract:
  - user_id is NEVER accepted from the client request body or query params.
  - It is always extracted from the JWT cookie via get_current_user.
  - Every Neo4j operation is scoped to current_user.id.

Endpoints:
  POST /api/rag/query                   — general question over all notes
  POST /api/rag/note/{note_id}/query    — question scoped to one note
  GET  /api/rag/note/{note_id}/related  — related notes and concepts
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.core.rate_limit import expensive_api_rate_limit
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services import rag_service
from backend.services.note_service import get_note
from backend.services.retrieval_service import get_note_related
from backend.services.ingestion_service import _neo4j_note_id
from backend.schemas import (
    RAGQueryRequest,
    NoteRAGQueryRequest,
    RAGQueryResponse,
    RAGSource,
    RetrievedChunkSchema,
    GraphRelationship,
    RelatedResponse,
    RelatedNote,
    GraphConcept,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


# ── General query ─────────────────────────────────────────────────────────────

@router.post("/query", response_model=RAGQueryResponse)
def rag_query(
    req: RAGQueryRequest,
    _: None = Depends(expensive_api_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask a question over the authenticated user's entire knowledge base.

    The request must NOT contain user_id — it is determined from the JWT cookie.

    Pipeline:
      1. user_id = current_user.id  (JWT, never client-supplied)
      2. Embed question
      3. User-scoped vector search
      4. User-scoped graph traversal
      5. Context fusion (user data only)
      6. Gemini LLM generation
      7. Return structured answer + sources + graph context
    """
    _ensure_services()

    result = rag_service.ask(
        question=req.question,
        user_id=current_user.id,
        top_k=req.top_k,
    )

    return _to_response(result)


# ── Note-scoped query ─────────────────────────────────────────────────────────

@router.post("/note/{note_id}/query", response_model=RAGQueryResponse)
def rag_note_query(
    note_id: str,
    req: NoteRAGQueryRequest,
    _: None = Depends(expensive_api_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask a question scoped to a specific note.

    - note_id must belong to the authenticated user (verified in MySQL).
    - Retrieval is restricted to that note's chunks only.
    - Graph traversal remains user-scoped.

    Returns 404 if the note does not exist or belongs to another user.
    """
    # Verify MySQL ownership before touching Neo4j
    note = get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    _ensure_services()

    result = rag_service.ask(
        question=req.question,
        user_id=current_user.id,
        top_k=req.top_k,
        note_id_filter=note_id,
    )

    return _to_response(result)


# ── Related knowledge ─────────────────────────────────────────────────────────

@router.get("/note/{note_id}/related", response_model=RelatedResponse)
def rag_note_related(
    note_id: str,
    max_notes: int = Query(5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return notes, concepts, and relationships related to a specific note.

    Discovers similarity by shared concepts in the knowledge graph.
    All returned data belongs exclusively to the authenticated user.

    Returns 404 if the note does not exist or belongs to another user.
    """
    # Verify MySQL ownership
    note = get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    _ensure_services()

    try:
        neo4j_note_id = _neo4j_note_id(current_user.id, note_id)
        related = get_note_related(
            neo4j_note_id=neo4j_note_id,
            user_id=current_user.id,
            max_notes=max(1, min(max_notes, 20)),
        )
    except Exception as e:
        logger.error("get_note_related failed for user=%s note=%s: %s",
                     current_user.id, note_id, e)
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    return RelatedResponse(
        note_id=note_id,
        related_notes=[
            RelatedNote(
                note_id=r["note_id"],
                title=r["title"],
                filename=r["filename"],
                shared_concepts=r.get("shared_concepts", 0),
            )
            for r in related.get("related_notes", [])
        ],
        concepts=[
            GraphConcept(name=c["name"])
            for c in related.get("concepts", [])
            if c.get("name")
        ],
        relationships=[
            GraphRelationship(
                source=r["source"],
                relationship=r["relationship"],
                target=r["target"],
            )
            for r in related.get("relationships", [])
            if r.get("source") and r.get("target")
        ],
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(result) -> RAGQueryResponse:
    """Convert RAGAnswer dataclass to RAGQueryResponse schema."""
    sources = [
        RAGSource(
            note_id=s.get("note_id", ""),
            title=s.get("title", ""),
            filename=s.get("filename", ""),
            chunk_id=s.get("chunk_id", ""),
            score=float(s.get("score", 0.0)),
        )
        for s in result.sources
    ]
    retrieved_chunks = [
        RetrievedChunkSchema(
            chunk_id=c.get("chunk_id", ""),
            note_id=c.get("note_id", ""),
            note_title=c.get("note_title", ""),
            note_filename=c.get("note_filename", ""),
            text=c.get("text", ""),
            score=float(c.get("score", 0.0)),
        )
        for c in result.retrieved_chunks
    ]
    relationships = [
        GraphRelationship(
            source=r.get("source", ""),
            relationship=r.get("relationship", ""),
            target=r.get("target", ""),
        )
        for r in result.relationships
        if r.get("source") and r.get("relationship") and r.get("target")
    ]
    return RAGQueryResponse(
        answer=result.answer,
        sources=sources,
        retrieved_chunks=retrieved_chunks,
        concepts=result.concepts,
        relationships=relationships,
        chunks_used=result.chunks_used,
        has_error=bool(result.error),
    )


def _ensure_services():
    """Lazily initialise embedding + LLM + Neo4j if not yet done by startup."""
    from backend.core.config import settings
    from backend.db.neo4j_client import init_driver, verify_connectivity
    from backend.services.embedding_service import init_embedding_service, _get_model
    from backend.services.llm_service import init_llm_service, _get_client

    try:
        verify_connectivity()
    except Exception:
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)

    try:
        _get_model()
    except RuntimeError:
        init_embedding_service(settings.embedding_model)

    try:
        _get_client()
    except RuntimeError:
        init_llm_service(settings.gemini_api_key or settings.groq_api_key, settings.gemini_llm_model)
