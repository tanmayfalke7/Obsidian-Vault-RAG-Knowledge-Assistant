"""
Pydantic schemas for API request/response validation.
"""
from typing import Optional
from pydantic import BaseModel, Field


# ── Query ─────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User's question")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of vector results")


class SourceReference(BaseModel):
    title: str
    filename: str
    score: Optional[float] = None


class GraphRelationship(BaseModel):
    source: str
    relationship: str
    target: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    relationships: list[GraphRelationship]
    chunks_used: int = 0
    retrieval_context: Optional[str] = None  # debug: full context sent to LLM


# ── Ingest ────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    vault_path: Optional[str] = Field(
        default=None,
        description="Optional custom vault path; defaults to data/vault",
    )
    reset: bool = Field(
        default=False,
        description="Delete existing project data before ingesting",
    )


class IngestResponse(BaseModel):
    success: bool
    notes_processed: int = 0
    chunks_created: int = 0
    concepts_created: int = 0
    relationships_created: int = 0
    embeddings_generated: int = 0
    errors: list[str] = []


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    neo4j: str
    gemini: str


# ── Stats ─────────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    notes: int = 0
    chunks: int = 0
    concepts: int = 0
    relationships: int = 0
    vector_index: str = "unknown"


# ── Graph Explorer ────────────────────────────────────────────────────────────

class GraphNeighbour(BaseModel):
    concept: str
    relationship: str
    direction: str  # "outgoing" | "incoming"


class GraphExploreResponse(BaseModel):
    concept: str
    neighbours: list[GraphNeighbour]
    found: bool


# ── Sources list ──────────────────────────────────────────────────────────────

class NoteInfo(BaseModel):
    id: str
    title: str
    filename: str
    chunk_count: int = 0
    concept_count: int = 0
