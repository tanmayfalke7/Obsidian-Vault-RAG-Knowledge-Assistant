"""
Pydantic schemas for all API requests and responses.
No schema contains a user_id field — user identity always comes from the JWT cookie.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(..., min_length=4, max_length=20, pattern=r"^\+?[A-Za-z0-9 .()-]+$")
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(ch.isalpha() for ch in v) or not any(ch.isdigit() for ch in v):
            raise ValueError("Password must contain at least one letter and one number.")
        return v


class LoginRequest(StrictBaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    is_active: bool
    created_at: datetime


class AuthMessageResponse(BaseModel):
    detail: str


# ── Folders ──────────────────────────────────────────────────────────────────

class FolderCreateRequest(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty_stripped(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Folder name cannot be empty or whitespace.")
        return v


class FolderUpdateRequest(StrictBaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    parent_id: Optional[str] = Field(None)  # None means "don't change"; use "" for root
    move_to_root: bool = False               # explicit flag to move to root (no parent)

    @field_validator("name")
    @classmethod
    def name_not_empty_stripped(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Folder name cannot be empty or whitespace.")
        return v


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FolderDetailResponse(BaseModel):
    """Folder with its immediate children and note count."""
    id: str
    name: str
    parent_id: Optional[str] = None
    children: list["FolderResponse"] = []
    note_count: int = 0
    created_at: datetime
    updated_at: datetime


class FolderTreeNode(BaseModel):
    """Recursive tree node for the full folder hierarchy."""
    id: str
    name: str
    parent_id: Optional[str] = None
    children: list["FolderTreeNode"] = []
    note_count: int = 0

    model_config = {"from_attributes": True}


# ── Notes ────────────────────────────────────────────────────────────────────

class NoteCreateRequest(StrictBaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=10_000_000)
    filename: Optional[str] = Field(None, max_length=500)
    folder_id: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_stripped(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty or whitespace.")
        return v

    @field_validator("filename")
    @classmethod
    def filename_must_be_md(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v and not v.lower().endswith(".md"):
            raise ValueError("filename must end with .md")
        return v


class NoteUpdateRequest(StrictBaseModel):
    title: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, max_length=10_000_000)
    folder_id: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_stripped(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty or whitespace.")
        return v


class NoteMoveRequest(StrictBaseModel):
    """Dedicated schema for moving a note to a different folder."""
    folder_id: Optional[str] = None  # None = move to root (unfiled)


class NoteResponse(BaseModel):
    id: str
    title: str
    filename: str
    source_type: str
    content: Optional[str] = None
    folder_id: Optional[str] = None
    is_ingested: bool = False
    created_at: datetime
    updated_at: datetime


class NoteListItem(BaseModel):
    """Compact note for list views."""
    id: str
    title: str
    filename: str
    source_type: str
    folder_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# Keep backward-compat alias
NoteListResponse = NoteListItem


class NoteListPage(BaseModel):
    """Paginated list of notes."""
    items: list[NoteListItem]
    total: int
    page: int
    page_size: int
    pages: int


class NoteSearchResult(BaseModel):
    """Note with a matched snippet and relevance rank."""
    id: str
    title: str
    filename: str
    folder_id: Optional[str] = None
    snippet: Optional[str] = None  # short excerpt around matched text
    match_field: str = "content"   # "title" | "filename" | "content"
    updated_at: datetime


class SearchResponse(BaseModel):
    query: str
    results: list[NoteSearchResult]
    total: int


# ── Upload / Ingest ───────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    note_id: str
    title: str
    filename: str
    ingested: bool
    chunks_created: int = 0
    embeddings_generated: int = 0
    errors: list[str] = []


class IngestStatusResponse(BaseModel):
    note_id: str
    ingested: bool
    chunks_created: int = 0
    embeddings_generated: int = 0
    errors: list[str] = []


ReindexResponse = IngestStatusResponse  # alias


# ── RAG ──────────────────────────────────────────────────────────────────────

class RAGQueryRequest(StrictBaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: Optional[int] = Field(None, ge=1, le=20)
    # note_id_filter accepted by note-specific endpoint, NOT by generic /query


class NoteRAGQueryRequest(StrictBaseModel):
    """Request for note-scoped RAG query."""
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: Optional[int] = Field(None, ge=1, le=20)


class RAGSource(BaseModel):
    """A source note that contributed to an RAG answer."""
    note_id: str
    title: str
    filename: str
    chunk_id: str
    score: float


class RetrievedChunkSchema(BaseModel):
    """A single retrieved chunk with its provenance."""
    chunk_id: str
    note_id: str
    note_title: str = ""
    note_filename: str = ""
    text: str
    score: float


class GraphConcept(BaseModel):
    """A concept node in the knowledge graph."""
    name: str


class GraphRelationship(BaseModel):
    source: str
    relationship: str
    target: str


class PathStep(BaseModel):
    """One step in a graph path — either a node or a relationship."""
    node: Optional[str] = None
    relationship: Optional[str] = None
    id: Optional[str] = None
    type: Optional[str] = None


class RAGQueryResponse(BaseModel):
    """Full GraphRAG response — frontend-friendly."""
    answer: str
    sources: list[RAGSource]
    retrieved_chunks: list[RetrievedChunkSchema]
    concepts: list[str]
    relationships: list[GraphRelationship]
    chunks_used: int = 0
    has_error: bool = False


# ── Graph explorer ────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    type: str                     # "note" | "concept" | "chunk"
    is_root: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str                     # relationship type


class GraphResponse(BaseModel):
    """Frontend-friendly graph of nodes and edges."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ConceptNeighbour(BaseModel):
    id: str
    name: str
    relationship: str
    direction: str                # "outgoing" | "incoming"


class ConceptDetail(BaseModel):
    concept_id: str
    name: str
    outgoing: list[ConceptNeighbour]
    incoming: list[ConceptNeighbour]


class PathResponse(BaseModel):
    source: str
    target: str
    found: bool
    steps: list[PathStep]


class RelatedNote(BaseModel):
    note_id: str
    title: str
    filename: str
    shared_concepts: int = 0


class RelatedResponse(BaseModel):
    note_id: str
    related_notes: list[RelatedNote]
    concepts: list[GraphConcept]
    relationships: list[GraphRelationship]


# ── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    mysql: str
    neo4j: str
    groq: str


# ── Backward-compat aliases ───────────────────────────────────────────────────
SourceReference = RAGSource
