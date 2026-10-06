"""
Note routes — complete CRUD, upload, move, and reindex.

Security rules:
  - user_id is NEVER accepted from the client.
  - Every endpoint uses current_user.id from the JWT cookie.
  - Ownership is enforced at the database query level.
  - A 404 is returned for resources that exist but belong to another user
    (no information leakage about other users' data).
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.dependencies import get_current_user
from backend.core.rate_limit import expensive_api_rate_limit
from backend.core.validation import sanitize_markdown_filename
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services import graph_service, ingestion_service, note_service
from backend.schemas import (
    IngestStatusResponse,
    NoteMoveRequest,
    NoteCreateRequest,
    NoteListItem,
    NoteListPage,
    NoteResponse,
    NoteUpdateRequest,
    UploadResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notes", tags=["notes"])


# ── List notes ────────────────────────────────────────────────────────────────

@router.get("", response_model=NoteListPage)
def list_notes(
    folder_id: Optional[str] = Query(None, description="Filter by folder UUID; omit for unfiled notes"),
    all_folders: bool = Query(False, description="If true, return notes from all folders"),
    search: Optional[str] = Query(None, max_length=200, description="Search query"),
    sort: str = Query("updated_at", description="Sort field: created_at | updated_at | title | filename"),
    order: Literal["asc", "desc"] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List the authenticated user's notes with pagination and sorting.

    - folder_id + all_folders=False → notes in that folder
    - folder_id omitted + all_folders=False → unfiled (root) notes
    - all_folders=True → all notes regardless of folder
    - search → filters by title/filename/content (user-scoped in SQL)
    """
    if search and search.strip():
        # Delegate to search which returns ranked results
        results = note_service.search_notes(db, current_user.id, search.strip())
        page_results = results[(page - 1) * page_size: page * page_size]
        return NoteListPage(
            items=[
                NoteListItem(
                    id=r["id"], title=r["title"], filename=r["filename"],
                    source_type="",  # not available in search result dict
                    folder_id=r["folder_id"],
                    created_at=r["updated_at"],  # fallback
                    updated_at=r["updated_at"],
                )
                for r in page_results
            ],
            total=len(results),
            page=page,
            page_size=page_size,
            pages=max(1, (len(results) + page_size - 1) // page_size),
        )

    paged = note_service.get_notes_paginated(
        db,
        user_id=current_user.id,
        folder_id=folder_id,
        include_all=all_folders,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    return NoteListPage(
        items=[
            NoteListItem(
                id=n.id, title=n.title, filename=n.filename,
                source_type=n.source_type, folder_id=n.folder_id,
                created_at=n.created_at, updated_at=n.updated_at,
            )
            for n in paged["items"]
        ],
        total=paged["total"],
        page=paged["page"],
        page_size=paged["page_size"],
        pages=paged["pages"],
    )


# ── Create note ────────────────────────────────────────────────────────────────

@router.post("", response_model=NoteResponse, status_code=201)
def create_note(
    req: NoteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new Markdown note and index it in Neo4j."""
    raw_filename = req.filename or f"{req.title.lower().replace(' ', '_')[:50]}.md"
    try:
        filename = sanitize_markdown_filename(raw_filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        note = note_service.create_note(
            db,
            user_id=current_user.id,
            title=req.title,
            filename=filename,
            content=req.content,
            folder_id=req.folder_id,
            source_type="created",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    stats = _run_ingestion(note, current_user.id)
    return _to_note_response(note, include_content=True, ingested=not stats.errors)


# ── Get single note ────────────────────────────────────────────────────────────

@router.get("/{note_id}", response_model=NoteResponse)
def get_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a note by ID including its full content. Returns 404 if not owned by caller."""
    note = note_service.get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _to_note_response(note, include_content=True)


# ── Update note ────────────────────────────────────────────────────────────────

@router.put("/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: str,
    req: NoteUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a note's title, content, or folder.
    If content changes: MySQL is updated first, then Neo4j is re-indexed.
    If only title/folder changes: no Neo4j re-index needed.
    """
    try:
        note = note_service.update_note(
            db,
            note_id=note_id,
            user_id=current_user.id,
            title=req.title,
            content=req.content,
            folder_id=req.folder_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    # Only re-index if content changed
    if req.content is not None:
        stats = _run_ingestion(note, current_user.id)
        return _to_note_response(note, include_content=True, ingested=not stats.errors)

    return _to_note_response(note, include_content=True)


# ── Move note ─────────────────────────────────────────────────────────────────

@router.patch("/{note_id}/move", response_model=NoteResponse)
def move_note(
    note_id: str,
    req: NoteMoveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Move a note to a different folder (or root with folder_id=null).
    No Neo4j re-index needed for a move-only operation.
    """
    try:
        note = note_service.move_note(
            db,
            note_id=note_id,
            user_id=current_user.id,
            folder_id=req.folder_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    return _to_note_response(note, include_content=False)


# ── Delete note ────────────────────────────────────────────────────────────────

@router.delete("/{note_id}", status_code=204)
def delete_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a note from MySQL and remove its Neo4j representation.
    Returns 404 if not owned by the authenticated user.
    """
    note = note_service.get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    # Delete from Neo4j first (best-effort; MySQL delete always happens)
    neo4j_note_id = f"{current_user.id}:{note_id}"
    try:
        graph_service.delete_note_neo4j(neo4j_note_id, current_user.id)
        logger.info("Deleted Neo4j note %s for user %s", neo4j_note_id, current_user.id)
    except Exception as e:
        logger.error("Neo4j delete failed for note %s: %s", note_id, e)
        # Do not abort — MySQL delete must still happen

    note_service.delete_note(db, note_id, current_user.id)
    return None


# ── Upload Markdown file ───────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_note(
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(default=None),
    title: Optional[str] = Form(default=None, max_length=500),
    _: None = Depends(expensive_api_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a Markdown (.md) file and index it in Neo4j.

    Validation:
      - Extension must be .md
      - File size ≤ MAX_MARKDOWN_FILE_SIZE_MB (from config)
      - Content must be decodable as UTF-8
    """
    try:
        filename = sanitize_markdown_filename(file.filename or "upload.md")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Extension validation
    if not filename.lower().endswith(".md"):
        raise HTTPException(
            status_code=422,
            detail="Only .md (Markdown) files are accepted. Other file types are not supported.",
        )

    # Read the file bytes
    raw_bytes = file.file.read()

    # File size validation
    max_bytes = settings.max_markdown_file_size_mb * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {settings.max_markdown_file_size_mb} MB.",
        )

    # UTF-8 decode
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail="File is not valid UTF-8. Only UTF-8 encoded Markdown files are supported.",
        )

    if not content.strip():
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    # Derive title from filename if not provided
    note_title = (title or "").strip() or filename[:-3].replace("_", " ").replace("-", " ")

    try:
        note = note_service.create_note(
            db,
            user_id=current_user.id,
            title=note_title,
            filename=filename,
            content=content,
            folder_id=folder_id,
            source_type="uploaded",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    stats = _run_ingestion(note, current_user.id)

    return UploadResponse(
        note_id=note.id,
        title=note.title,
        filename=note.filename,
        ingested=not stats.errors,
        chunks_created=stats.chunks_created,
        embeddings_generated=stats.embeddings_generated,
        errors=stats.errors,
    )


# ── Reindex ────────────────────────────────────────────────────────────────────

@router.post("/{note_id}/reindex", response_model=IngestStatusResponse)
def reindex_note(
    note_id: str,
    _: None = Depends(expensive_api_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Re-run Neo4j ingestion for a note using its current MySQL content.
    Old chunks/relationships are removed and rebuilt from scratch.
    """
    note = note_service.get_note(db, note_id, current_user.id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    stats = _run_ingestion(note, current_user.id)

    return IngestStatusResponse(
        note_id=note_id,
        ingested=not stats.errors,
        chunks_created=stats.chunks_created,
        embeddings_generated=stats.embeddings_generated,
        errors=stats.errors,
    )


# ── Internal helpers ───────────────────────────────────────────────────────────

def _run_ingestion(note, user_id: str):
    """
    Lazily ensure services and run user-scoped ingestion.
    Idempotent: safe to call on create and on update.
    """
    from backend.services.embedding_service import _get_model, init_embedding_service

    # Lazy init only if not already initialised by startup
    try:
        _get_model()
    except RuntimeError:
        init_embedding_service(settings.embedding_model)

    # Ensure Neo4j schema (IF NOT EXISTS guards make these idempotent)
    graph_service.create_constraints_and_indexes()
    graph_service.create_vector_index(
        settings.vector_index_name,
        settings.embedding_dimensions,
    )
    graph_service.upsert_user_node(user_id, name="")

    return ingestion_service.ingest_note(
        note_id=note.id,
        user_id=user_id,
        content=note.content,
        title=note.title,
        filename=note.filename,
    )


def _to_note_response(note, include_content: bool = False, ingested: bool = False) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        title=note.title,
        filename=note.filename,
        source_type=note.source_type,
        content=note.content if include_content else None,
        folder_id=note.folder_id,
        is_ingested=ingested,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )
