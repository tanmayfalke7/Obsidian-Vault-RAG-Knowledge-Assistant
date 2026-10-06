"""
Folder service — MySQL CRUD for user-owned folders.

Every operation filters by user_id. No cross-user access is possible.

Supports:
  - Unlimited nesting via parent_id
  - Move-folder with cycle detection
  - Unique name constraint at each (user, parent) level
  - Recursive list for tree building
  - Safe deletion with configurable note disposition
"""
from __future__ import annotations

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import Folder

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _all_descendant_ids(db: Session, folder_id: str, user_id: str) -> set[str]:
    """Return the set of all descendant folder IDs (not including folder_id itself)."""
    descendants: set[str] = set()
    stack = [folder_id]
    while stack:
        current = stack.pop()
        children = db.execute(
            select(Folder.id).where(
                Folder.parent_id == current, Folder.user_id == user_id
            )
        ).scalars().all()
        for child_id in children:
            if child_id not in descendants:
                descendants.add(child_id)
                stack.append(child_id)
    return descendants


# ── Basic CRUD ────────────────────────────────────────────────────────────────

def create_folder(
    db: Session,
    user_id: str,
    name: str,
    parent_id: str | None = None,
) -> Folder:
    """
    Create a new folder owned by user_id.
    Validates parent ownership and unique name at same level.
    Raises ValueError on conflict.
    """
    name = name.strip()
    if not name:
        raise ValueError("Folder name cannot be empty.")

    # Verify parent ownership
    if parent_id:
        parent = get_folder(db, parent_id, user_id)
        if parent is None:
            raise ValueError("Parent folder not found or does not belong to this user.")

    # Check duplicate name at same level
    duplicate_query = select(Folder).where(Folder.user_id == user_id, Folder.name == name)
    if parent_id:
        duplicate_query = duplicate_query.where(Folder.parent_id == parent_id)
    else:
        duplicate_query = duplicate_query.where(Folder.parent_id.is_(None))

    existing = db.execute(duplicate_query).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            f"A folder named '{name}' already exists at this location."
        )

    folder = Folder(
        id=str(uuid.uuid4()),
        user_id=user_id,
        parent_id=parent_id,
        name=name,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    logger.info("Created folder '%s' (%s) for user %s", name, folder.id, user_id)
    return folder


def get_folder(db: Session, folder_id: str, user_id: str) -> Folder | None:
    """Get a folder by ID. ALWAYS filters by user_id."""
    return db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    ).scalar_one_or_none()


def get_folder_with_details(db: Session, folder_id: str, user_id: str) -> dict | None:
    """
    Return a folder together with its direct children and note count.
    Returns None if not found / not owned by user.
    """
    folder = db.execute(
        select(Folder)
        .options(selectinload(Folder.children), selectinload(Folder.notes))
        .where(Folder.id == folder_id, Folder.user_id == user_id)
    ).scalar_one_or_none()

    if folder is None:
        return None

    # Filter children that belong to the same user (safety double-check)
    children = [c for c in (folder.children or []) if c.user_id == user_id]
    return {
        "folder": folder,
        "children": children,
        "note_count": len([n for n in (folder.notes or []) if n.user_id == user_id]),
    }


def get_folders_for_user(
    db: Session,
    user_id: str,
    parent_id: str | None = None,
) -> list[Folder]:
    """
    List direct-child folders for user_id at a given parent level.
    parent_id=None returns root-level folders.
    """
    q = select(Folder).where(Folder.user_id == user_id)
    if parent_id is not None:
        q = q.where(Folder.parent_id == parent_id)
    else:
        q = q.where(Folder.parent_id.is_(None))
    q = q.order_by(Folder.name)
    return list(db.execute(q).scalars().all())


def get_all_folders_for_user(db: Session, user_id: str) -> list[Folder]:
    """Fetch ALL folders for user_id (for tree building)."""
    return list(
        db.execute(
            select(Folder).where(Folder.user_id == user_id).order_by(Folder.name)
        )
        .scalars()
        .all()
    )


def build_folder_tree(db: Session, user_id: str) -> list[dict]:
    """
    Build a nested folder tree for the user.
    Returns a list of root-level FolderTreeNode-compatible dicts.
    """
    # Load all at once, then assemble in Python
    all_folders = get_all_folders_for_user(db, user_id)

    # Count notes per folder
    from backend.db.models import Note
    from sqlalchemy import func
    note_counts_rows = db.execute(
        select(Note.folder_id, func.count(Note.id).label("cnt"))
        .where(Note.user_id == user_id, Note.folder_id.is_not(None))
        .group_by(Note.folder_id)
    ).all()
    note_count_map: dict[str, int] = {row.folder_id: row.cnt for row in note_counts_rows}

    # Build id → node map
    nodes: dict[str, dict] = {}
    for f in all_folders:
        nodes[f.id] = {
            "id": f.id,
            "name": f.name,
            "parent_id": f.parent_id,
            "children": [],
            "note_count": note_count_map.get(f.id, 0),
        }

    # Wire children
    roots: list[dict] = []
    for node in nodes.values():
        pid = node["parent_id"]
        if pid and pid in nodes:
            nodes[pid]["children"].append(node)
        elif pid is None:
            roots.append(node)

    # Sort children alphabetically at each level
    def _sort(node_list: list[dict]) -> None:
        node_list.sort(key=lambda n: n["name"].lower())
        for n in node_list:
            _sort(n["children"])

    _sort(roots)
    return roots


def update_folder(
    db: Session,
    folder_id: str,
    user_id: str,
    name: str | None = None,
    new_parent_id: str | None = None,
    move_to_root: bool = False,
) -> Folder | None:
    """
    Rename and/or move a folder.

    - name: new name (None = keep current)
    - new_parent_id: new parent folder ID (None = keep current, unless move_to_root)
    - move_to_root: if True, detach from any parent (make root-level)

    Raises ValueError for:
      - Self-parent (moving folder inside itself)
      - Descendant-parent (moving folder inside one of its descendants → cycle)
      - Duplicate name at destination level
    """
    folder = get_folder(db, folder_id, user_id)
    if folder is None:
        return None

    # ── Move logic ──────────────────────────────────────────────────────────
    target_parent: str | None = folder.parent_id  # default: no change

    if move_to_root:
        target_parent = None
    elif new_parent_id is not None:
        if new_parent_id == folder_id:
            raise ValueError("A folder cannot be moved inside itself.")

        # Verify target parent ownership
        target = get_folder(db, new_parent_id, user_id)
        if target is None:
            raise ValueError(
                "Destination folder not found or does not belong to this user."
            )

        # Prevent moving into a descendant (cycle detection)
        descendants = _all_descendant_ids(db, folder_id, user_id)
        if new_parent_id in descendants:
            raise ValueError(
                "Cannot move a folder into one of its own descendants."
            )

        target_parent = new_parent_id

    # ── Name logic ───────────────────────────────────────────────────────────
    new_name = folder.name
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ValueError("Folder name cannot be empty.")

    # Duplicate check at destination level (only if name or parent changed)
    if new_name != folder.name or target_parent != folder.parent_id:
        q = select(Folder).where(
            Folder.user_id == user_id,
            Folder.name == new_name,
            Folder.id != folder_id,
        )
        if target_parent is not None:
            q = q.where(Folder.parent_id == target_parent)
        else:
            q = q.where(Folder.parent_id.is_(None))

        conflict = db.execute(q).scalar_one_or_none()
        if conflict is not None:
            raise ValueError(
                f"A folder named '{new_name}' already exists at the destination."
            )

    folder.name = new_name
    folder.parent_id = target_parent
    db.commit()
    db.refresh(folder)
    logger.info(
        "Updated folder %s for user %s: name='%s' parent=%s",
        folder_id, user_id, new_name, target_parent,
    )
    return folder


def delete_folder(
    db: Session,
    folder_id: str,
    user_id: str,
    recursive: bool = False,
) -> bool:
    """
    Delete a folder.

    recursive=False (default):
      - Refuse if folder has notes or subfolders (safe default)
      - Returns False with a ValueError indicating non-empty
      - Notes are NEVER silently orphaned

    recursive=True:
      - Delete the folder and ALL descendants
      - Unlink (set folder_id=NULL) all notes in deleted folders
        (notes are preserved in MySQL but become unfiled)
      - All deletion happens in a single transaction
    """
    folder = get_folder(db, folder_id, user_id)
    if folder is None:
        return False

    from backend.db.models import Note

    if recursive:
        # Collect all folder IDs to delete (self + all descendants)
        to_delete_ids = {folder_id} | _all_descendant_ids(db, folder_id, user_id)

        # Unlink notes in all these folders (preserve the notes)
        notes = db.execute(
            select(Note).where(
                Note.folder_id.in_(to_delete_ids),
                Note.user_id == user_id,
            )
        ).scalars().all()
        for note in notes:
            note.folder_id = None

        # Delete folders bottom-up (deepest first to respect FK constraints)
        # SQLAlchemy cascade or ordering: easiest is delete all at once
        all_folder_objs = db.execute(
            select(Folder).where(
                Folder.id.in_(to_delete_ids),
                Folder.user_id == user_id,
            )
        ).scalars().all()
        # Delete children before parents to avoid FK issues
        # Sort so leaves come first (no children present in to_delete_ids)
        sorted_folders = sorted(
            all_folder_objs,
            key=lambda f: (f.parent_id is not None),
            reverse=True,
        )
        for f in sorted_folders:
            db.delete(f)
        db.commit()
        logger.info(
            "Recursively deleted folder %s and %d descendants for user %s",
            folder_id, len(to_delete_ids) - 1, user_id,
        )
    else:
        # Non-recursive: refuse if folder has children or notes
        child_count = db.execute(
            select(Folder).where(
                Folder.parent_id == folder_id, Folder.user_id == user_id
            )
        ).scalars().first()
        note_count = db.execute(
            select(Note).where(
                Note.folder_id == folder_id, Note.user_id == user_id
            )
        ).scalars().first()

        if child_count is not None or note_count is not None:
            raise ValueError(
                "Folder is not empty. Move or delete its contents first, "
                "or use recursive=True to delete everything."
            )

        db.delete(folder)
        db.commit()
        logger.info("Deleted empty folder %s for user %s", folder_id, user_id)

    return True
