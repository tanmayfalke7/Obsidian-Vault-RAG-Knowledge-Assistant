"""
Folder routes — complete CRUD + tree + move.

Security: user_id always comes from the JWT cookie; never from the request body.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services import folder_service
from backend.schemas import (
    FolderCreateRequest,
    FolderDetailResponse,
    FolderResponse,
    FolderTreeNode,
    FolderUpdateRequest,
    NoteListItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/folders", tags=["folders"])


# ── Tree ──────────────────────────────────────────────────────────────────────

@router.get("/tree", response_model=list[FolderTreeNode])
def folder_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the full nested folder tree for the authenticated user.

    Response shape:
    [
      {id, name, parent_id, note_count, children: [
        {id, name, parent_id, note_count, children: [...]}
      ]}
    ]

    Suitable for rendering a sidebar navigation tree.
    """
    tree = folder_service.build_folder_tree(db, current_user.id)
    return tree


# ── List (flat) ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[FolderResponse])
def list_folders(
    parent_id: Optional[str] = Query(None, description="List children of this folder; omit for root"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List the authenticated user's folders at a specific level.
    parent_id=None (default) returns root-level folders only.
    """
    folders = folder_service.get_folders_for_user(db, current_user.id, parent_id)
    return [
        FolderResponse(
            id=f.id, name=f.name, parent_id=f.parent_id,
            created_at=f.created_at, updated_at=f.updated_at,
        )
        for f in folders
    ]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=FolderResponse, status_code=201)
def create_folder(
    req: FolderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new folder.

    - parent_id=null → root folder
    - parent_id=<uuid> → child of that folder (must belong to current user)
    - Duplicate names at the same level are rejected with 409.
    """
    try:
        folder = folder_service.create_folder(
            db,
            user_id=current_user.id,
            name=req.name,
            parent_id=req.parent_id,
        )
    except ValueError as e:
        msg = str(e)
        status_code = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)

    return FolderResponse(
        id=folder.id, name=folder.name, parent_id=folder.parent_id,
        created_at=folder.created_at, updated_at=folder.updated_at,
    )


# ── Get detail ────────────────────────────────────────────────────────────────

@router.get("/{folder_id}", response_model=FolderDetailResponse)
def get_folder(
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a folder by ID with its direct children and note count.
    Returns 404 if the folder does not belong to the authenticated user.
    """
    details = folder_service.get_folder_with_details(db, folder_id, current_user.id)
    if details is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder = details["folder"]
    children = details["children"]

    return FolderDetailResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        children=[
            FolderResponse(
                id=c.id, name=c.name, parent_id=c.parent_id,
                created_at=c.created_at, updated_at=c.updated_at,
            )
            for c in children
        ],
        note_count=details["note_count"],
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ── Update (rename / move) ─────────────────────────────────────────────────────

@router.put("/{folder_id}", response_model=FolderResponse)
def update_folder(
    folder_id: str,
    req: FolderUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Rename and/or move a folder.

    Request body:
      {
        "name": "new name",         (optional — omit to keep current)
        "parent_id": "<uuid>",      (optional — omit to keep current parent)
        "move_to_root": true        (set true to detach from any parent)
      }

    Errors:
      - 400: invalid name, self-parent, or descendant-parent (cycle)
      - 404: folder not found or not owned
      - 409: duplicate name at destination
    """
    try:
        folder = folder_service.update_folder(
            db,
            folder_id=folder_id,
            user_id=current_user.id,
            name=req.name,
            new_parent_id=req.parent_id,
            move_to_root=req.move_to_root,
        )
    except ValueError as e:
        msg = str(e)
        status_code = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)

    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    return FolderResponse(
        id=folder.id, name=folder.name, parent_id=folder.parent_id,
        created_at=folder.created_at, updated_at=folder.updated_at,
    )


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{folder_id}", status_code=204)
def delete_folder(
    folder_id: str,
    recursive: bool = Query(
        False,
        description=(
            "If true, delete the folder and all its descendants. "
            "Notes inside are unlinked (preserved). "
            "If false (default), deletion is refused if folder is non-empty."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a folder.

    recursive=false (default):
      - Fails with 409 if the folder contains notes or subfolders.
      - Safe default — prevents accidental data loss.

    recursive=true:
      - Deletes the folder and all descendant folders.
      - All notes inside are unlinked (set to unfiled) but NOT deleted.
      - Returns 204 on success.
    """
    try:
        deleted = folder_service.delete_folder(
            db,
            folder_id=folder_id,
            user_id=current_user.id,
            recursive=recursive,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Folder not found")

    return None


# ── Notes in folder ────────────────────────────────────────────────────────────

@router.get("/{folder_id}/notes", response_model=list[NoteListItem])
def list_folder_notes(
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List notes in a specific folder (must be owned by the authenticated user).
    """
    # Verify folder ownership first
    folder = folder_service.get_folder(db, folder_id, current_user.id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    from backend.services.note_service import get_notes_for_user
    notes = get_notes_for_user(db, current_user.id, folder_id=folder_id)
    return [
        NoteListItem(
            id=n.id, title=n.title, filename=n.filename,
            source_type=n.source_type, folder_id=n.folder_id,
            created_at=n.created_at, updated_at=n.updated_at,
        )
        for n in notes
    ]
