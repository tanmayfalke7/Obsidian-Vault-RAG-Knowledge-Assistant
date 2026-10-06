"""
Note service — MySQL CRUD for user-owned Markdown notes.

Every operation filters by user_id. No cross-user access is possible.

Features:
  - Paginated, sortable list with optional folder filter
  - Full-text search with ranked snippets
  - Move note between folders
  - Content-only update triggers re-ingestion
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Literal
from sqlalchemy import select, or_, func, text, asc, desc
from sqlalchemy.orm import Session

from backend.db.models import Note, Folder

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SORTABLE_COLUMNS: dict[str, any] = {
    "created_at": Note.created_at,
    "updated_at": Note.updated_at,
    "title": Note.title,
    "filename": Note.filename,
}
SNIPPET_LENGTH = 200  # characters


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_snippet(text_body: str, query: str, length: int = SNIPPET_LENGTH) -> str:
    """
    Extract a short snippet of text_body around the first occurrence of query.
    Returns empty string if not found.
    """
    idx = text_body.lower().find(query.lower())
    if idx == -1:
        return ""
    start = max(0, idx - length // 4)
    end = min(len(text_body), idx + length * 3 // 4)
    snippet = text_body[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text_body):
        snippet = snippet + "…"
    return snippet


def _verify_folder_ownership(db: Session, folder_id: str | None, user_id: str) -> None:
    """Raise ValueError if folder_id is non-null and doesn't belong to user_id."""
    if folder_id:
        folder = db.execute(
            select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
        ).scalar_one_or_none()
        if folder is None:
            raise ValueError("Folder not found or does not belong to this user.")


# ── Basic CRUD ────────────────────────────────────────────────────────────────

def create_note(
    db: Session,
    user_id: str,
    title: str,
    filename: str,
    content: str,
    folder_id: str | None = None,
    source_type: str = "uploaded",
) -> Note:
    """Create a new note owned by user_id."""
    _verify_folder_ownership(db, folder_id, user_id)

    note = Note(
        id=str(uuid.uuid4()),
        user_id=user_id,
        folder_id=folder_id,
        title=title.strip(),
        filename=filename,
        content=content,
        source_type=source_type,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    logger.info("Created note '%s' (%s) for user %s", title, note.id, user_id)
    return note


def get_note(db: Session, note_id: str, user_id: str) -> Note | None:
    """Get a note by ID. ALWAYS filters by user_id — no cross-user access."""
    return db.execute(
        select(Note).where(Note.id == note_id, Note.user_id == user_id)
    ).scalar_one_or_none()


def get_notes_for_user(
    db: Session,
    user_id: str,
    folder_id: str | None = None,
    include_all: bool = False,
) -> list[Note]:
    """
    List notes for user_id.
    - folder_id=None + include_all=False: unfiled notes only
    - folder_id=<id>: notes in that folder
    - include_all=True: all notes regardless of folder
    """
    q = select(Note).where(Note.user_id == user_id)
    if include_all:
        pass  # no folder filter
    elif folder_id is not None:
        q = q.where(Note.folder_id == folder_id)
    else:
        q = q.where(Note.folder_id.is_(None))
    q = q.order_by(Note.updated_at.desc())
    return list(db.execute(q).scalars().all())


def get_notes_paginated(
    db: Session,
    user_id: str,
    folder_id: str | None = None,
    include_all: bool = False,
    sort: str = "updated_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return paginated notes with total count.
    All filtering done at DB level — never fetches all then filters.

    Returns:
        {items, total, page, page_size, pages}
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    sort_col = SORTABLE_COLUMNS.get(sort, Note.updated_at)
    order_fn = asc if order == "asc" else desc

    q = select(Note).where(Note.user_id == user_id)
    q_count = select(func.count(Note.id)).where(Note.user_id == user_id)

    if include_all:
        pass
    elif folder_id is not None:
        q = q.where(Note.folder_id == folder_id)
        q_count = q_count.where(Note.folder_id == folder_id)
    else:
        q = q.where(Note.folder_id.is_(None))
        q_count = q_count.where(Note.folder_id.is_(None))

    total = db.execute(q_count).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)

    items = list(
        db.execute(
            q.order_by(order_fn(sort_col))
              .offset((page - 1) * page_size)
              .limit(page_size)
        )
        .scalars()
        .all()
    )

    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


def get_all_notes_for_user(db: Session, user_id: str) -> list[Note]:
    """List ALL notes for user_id regardless of folder."""
    return list(
        db.execute(
            select(Note).where(Note.user_id == user_id).order_by(Note.updated_at.desc())
        )
        .scalars()
        .all()
    )


def update_note(
    db: Session,
    note_id: str,
    user_id: str,
    title: str | None = None,
    content: str | None = None,
    folder_id: str | None = None,
) -> Note | None:
    """Update a note. ALWAYS filters by user_id."""
    note = get_note(db, note_id, user_id)
    if note is None:
        return None

    if title is not None:
        note.title = title.strip()
    if content is not None:
        note.content = content
    if folder_id is not None:
        _verify_folder_ownership(db, folder_id, user_id)
        note.folder_id = folder_id or None
    # Explicit move to None (root) handled by move_note

    db.commit()
    db.refresh(note)
    return note


def move_note(
    db: Session,
    note_id: str,
    user_id: str,
    folder_id: str | None,
) -> Note | None:
    """
    Move a note to a different folder (or to root with folder_id=None).
    Verifies both note ownership and target folder ownership.
    """
    note = get_note(db, note_id, user_id)
    if note is None:
        return None

    # Verify target folder ownership (None = root, always allowed)
    if folder_id is not None:
        _verify_folder_ownership(db, folder_id, user_id)

    note.folder_id = folder_id
    db.commit()
    db.refresh(note)
    logger.info("Moved note %s to folder %s for user %s", note_id, folder_id, user_id)
    return note


def delete_note(db: Session, note_id: str, user_id: str) -> bool:
    """Delete a note from MySQL. ALWAYS filters by user_id."""
    note = get_note(db, note_id, user_id)
    if note is None:
        return False
    db.delete(note)
    db.commit()
    logger.info("Deleted note %s for user %s", note_id, user_id)
    return True


# ── Search ────────────────────────────────────────────────────────────────────

def search_notes(
    db: Session,
    user_id: str,
    query: str,
    limit: int = 50,
) -> list[dict]:
    """
    Search user's notes by title, filename, and content.
    Returns results with snippet and match_field for ranking.

    Ranking (priority):
      1. Title match
      2. Filename match
      3. Content match

    The SQL query ALWAYS includes user_id — never fetches all then filters.
    """
    q_lower = f"%{query.lower()}%"

    # Single query with OR across fields, user-scoped
    notes = list(
        db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(
                    func.lower(Note.title).like(q_lower),
                    func.lower(Note.filename).like(q_lower),
                    func.lower(Note.content).like(q_lower),
                ),
            )
            .order_by(Note.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    results = []
    for note in notes:
        # Determine match field and build snippet
        title_match = query.lower() in note.title.lower()
        filename_match = query.lower() in note.filename.lower()
        content_match = query.lower() in note.content.lower()

        if title_match:
            match_field = "title"
            snippet = note.title
            rank = 1
        elif filename_match:
            match_field = "filename"
            snippet = note.filename
            rank = 2
        else:
            match_field = "content"
            snippet = _extract_snippet(note.content, query)
            rank = 3

        results.append({
            "id": note.id,
            "title": note.title,
            "filename": note.filename,
            "folder_id": note.folder_id,
            "snippet": snippet,
            "match_field": match_field,
            "_rank": rank,
            "updated_at": note.updated_at,
        })

    # Sort by rank (title > filename > content), then by updated_at desc
    results.sort(key=lambda r: (r["_rank"], -r["updated_at"].timestamp()))
    for r in results:
        del r["_rank"]

    return results


def count_notes(db: Session, user_id: str) -> int:
    """Count notes for a user."""
    result = db.execute(
        select(func.count(Note.id)).where(Note.user_id == user_id)
    )
    return result.scalar() or 0
