"""
Graph explorer routes — expose the user's knowledge graph to the frontend.

Security contract:
  - user_id is NEVER accepted from the client.
  - Every endpoint checks note/concept ownership via user_id from the JWT.
  - Neo4j queries always include user_id as a WHERE constraint.
  - Returns 404 (not 403) for resources that exist but belong to another user
    (avoids information leakage about other tenants).

Endpoints:
  GET /api/graph/note/{note_id}           — graph centred on a note
  GET /api/graph/concept/{concept_id}     — graph centred on a concept
  GET /api/graph/neighbors/{concept_id}   — immediate neighbours of a concept
  GET /api/graph/path                     — shortest path between two concepts
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.dependencies import get_current_user
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services.note_service import get_note
from backend.services.retrieval_service import (
    get_note_graph,
    get_concept_graph,
    get_concept_neighbours,
    find_path,
)
from backend.services.ingestion_service import _neo4j_note_id, _neo4j_concept_id
from backend.schemas import (
    GraphResponse,
    GraphNode,
    GraphEdge,
    ConceptDetail,
    ConceptNeighbour,
    PathResponse,
    PathStep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["graph"])


# ── Note graph ────────────────────────────────────────────────────────────────

@router.get("/note/{note_id}", response_model=GraphResponse)
def note_graph(
    note_id: str,
    max_nodes: int = Query(default=None, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the knowledge graph centred on a note.

    Nodes include the note, its concepts, and related concepts (1-hop).
    Edges are concept-to-concept relationships.
    All nodes belong to the authenticated user.

    Returns 404 if the note does not exist or belongs to another user.
    """
    note = get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    _ensure_neo4j()

    neo4j_note_id = _neo4j_note_id(current_user.id, note_id)
    try:
        raw = get_note_graph(
            neo4j_note_id,
            user_id=current_user.id,
            max_nodes=max_nodes or settings.graph_max_nodes,
        )
    except Exception as e:
        logger.error("get_note_graph failed user=%s note=%s: %s", current_user.id, note_id, e)
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    return GraphResponse(
        nodes=[
            GraphNode(
                id=n["id"],
                label=n["label"],
                type=n["type"],
                is_root=n.get("is_root", False),
            )
            for n in raw.get("nodes", [])
        ],
        edges=[
            GraphEdge(source=e["source"], target=e["target"], type=e["type"])
            for e in raw.get("edges", [])
            if e.get("source") and e.get("target")
        ],
    )


# ── Concept graph ─────────────────────────────────────────────────────────────

@router.get("/concept/{concept_id}", response_model=GraphResponse)
def concept_graph(
    concept_id: str,
    depth: int = Query(default=None, ge=1, le=4),
    max_nodes: int = Query(default=None, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the knowledge graph centred on a concept.

    concept_id must be the Neo4j concept ID (format: {user_id}:concept:{slug}).
    The endpoint verifies that the concept belongs to the authenticated user
    by checking that user_id is embedded in the concept_id and confirmed in Neo4j.

    Returns 404 if the concept does not exist or belongs to another user.
    """
    # Security: concept_id must start with current user's ID (embedded in the deterministic ID)
    if not concept_id.startswith(current_user.id + ":"):
        raise HTTPException(status_code=404, detail="Concept not found")

    _ensure_neo4j()

    try:
        raw = get_concept_graph(
            concept_id=concept_id,
            user_id=current_user.id,
            depth=depth or settings.graph_max_depth,
            max_nodes=max_nodes or settings.graph_max_nodes,
        )
    except Exception as e:
        logger.error("get_concept_graph failed user=%s concept=%s: %s",
                     current_user.id, concept_id, e)
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    if not raw.get("nodes"):
        raise HTTPException(status_code=404, detail="Concept not found")

    return GraphResponse(
        nodes=[
            GraphNode(
                id=n["id"],
                label=n["label"],
                type=n.get("type", "concept"),
                is_root=n.get("is_root", False),
            )
            for n in raw.get("nodes", [])
        ],
        edges=[
            GraphEdge(source=e["source"], target=e["target"], type=e["type"])
            for e in raw.get("edges", [])
            if e.get("source") and e.get("target")
        ],
    )


# ── Concept neighbours ────────────────────────────────────────────────────────

@router.get("/neighbors/{concept_id}", response_model=ConceptDetail)
def concept_neighbors(
    concept_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the immediate (1-hop) neighbours of a concept with direction info.

    concept_id format: {user_id}:concept:{slug}

    Returns:
      {concept_id, name, outgoing: [...], incoming: [...]}
    """
    if not concept_id.startswith(current_user.id + ":"):
        raise HTTPException(status_code=404, detail="Concept not found")

    _ensure_neo4j()

    try:
        raw = get_concept_neighbours(concept_id=concept_id, user_id=current_user.id)
    except Exception as e:
        logger.error("get_concept_neighbours failed user=%s concept=%s: %s",
                     current_user.id, concept_id, e)
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    if not raw.get("name") and not raw.get("outgoing") and not raw.get("incoming"):
        raise HTTPException(status_code=404, detail="Concept not found")

    return ConceptDetail(
        concept_id=raw["concept_id"],
        name=raw["name"],
        outgoing=[
            ConceptNeighbour(
                id=n["id"],
                name=n["name"],
                relationship=n["relationship"],
                direction="outgoing",
            )
            for n in raw.get("outgoing", [])
            if n.get("id") and n.get("relationship")
        ],
        incoming=[
            ConceptNeighbour(
                id=n["id"],
                name=n["name"],
                relationship=n["relationship"],
                direction="incoming",
            )
            for n in raw.get("incoming", [])
            if n.get("id") and n.get("relationship")
        ],
    )


# ── Path finding ──────────────────────────────────────────────────────────────

@router.get("/path", response_model=PathResponse)
def graph_path(
    source: str = Query(..., min_length=1, max_length=200,
                        description="Source concept name"),
    target: str = Query(..., min_length=1, max_length=200,
                        description="Target concept name"),
    max_depth: int = Query(default=None, ge=1, le=6),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Find the shortest path between two concepts in the user's knowledge graph.

    Both source and target are matched by name (case-insensitive).
    Only paths within the authenticated user's graph are searched.

    Example response for RAG → Semantic Search:
      [
        {"node": "RAG",           "type": "Concept"},
        {"relationship": "USES"},
        {"node": "Embeddings",    "type": "Concept"},
        {"relationship": "ENABLES"},
        {"node": "Semantic Search","type": "Concept"}
      ]
    """
    _ensure_neo4j()

    try:
        steps = find_path(
            source_name=source.strip(),
            target_name=target.strip(),
            user_id=current_user.id,
            max_depth=max_depth or settings.graph_max_depth,
        )
    except Exception as e:
        logger.error("find_path failed user=%s src=%s tgt=%s: %s",
                     current_user.id, source, target, e)
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    return PathResponse(
        source=source,
        target=target,
        found=bool(steps),
        steps=[
            PathStep(
                node=s.get("node"),
                relationship=s.get("relationship"),
                id=s.get("id"),
                type=s.get("type"),
            )
            for s in steps
        ],
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _ensure_neo4j():
    """Lazily initialise Neo4j if not yet done by startup."""
    from backend.db.neo4j_client import init_driver, verify_connectivity
    from backend.core.config import settings as cfg
    try:
        verify_connectivity()
    except Exception:
        init_driver(cfg.neo4j_uri, cfg.neo4j_username, cfg.neo4j_password)
