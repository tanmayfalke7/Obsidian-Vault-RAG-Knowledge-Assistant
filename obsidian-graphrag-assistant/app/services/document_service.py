"""
Document upload, storage, and CRUD.
Files are saved to the upload directory; metadata lives in SQLite.
Ingestion into Neo4j is triggered separately.
"""
import hashlib
import logging
import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.database import Document, User

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".html"}
ALLOWED_CONTENT_TYPES = {
    "text/markdown", "text/plain", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/html",
}


def _safe_filename(filename: str) -> str:
    """Remove path traversal, keep only name+ext."""
    return Path(filename).name


async def save_upload(
    db: AsyncSession,
    file: UploadFile,
    user: User,
    title: str | None = None,
    tags: str | None = None,
    description: str | None = None,
    folder_id: str | None = None,
) -> Document:
    """Save an uploaded file to disk and create a Document record."""
    original_name = _safe_filename(file.filename or "document.md")
    suffix = Path(original_name).suffix.lower()

    # User-specific subdirectory
    user_dir = settings.upload_path / user.id
    user_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename to avoid collisions
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()[:12]
    unique_name = f"{file_hash}_{original_name}"
    dest = user_dir / unique_name

    dest.write_bytes(content)
    file_size = len(content)

    doc = Document(
        title=(title or Path(original_name).stem).strip(),
        filename=unique_name,
        original_filename=original_name,
        file_path=str(dest.relative_to(settings.project_root)),
        file_size=file_size,
        content_type=file.content_type or "text/markdown",
        tags=tags,
        description=description,
        owner_id=user.id,
        folder_id=folder_id or None,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    logger.info("Document saved: %s for user %s", unique_name, user.id)
    return doc


async def get_documents_for_user(
    db: AsyncSession,
    user_id: str,
    folder_id: str | None = None,
) -> list[Document]:
    q = select(Document).where(Document.owner_id == user_id)
    if folder_id is not None:
        q = q.where(Document.folder_id == folder_id)
    else:
        q = q.where(Document.folder_id.is_(None))
    q = q.order_by(Document.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_all_documents_for_user(db: AsyncSession, user_id: str) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.owner_id == user_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(
    db: AsyncSession, doc_id: str, user_id: str
) -> Document | None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.owner_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_document(
    db: AsyncSession, doc_id: str, user_id: str
) -> bool:
    doc = await get_document(db, doc_id, user_id)
    if doc is None:
        return False
    # Remove file from disk
    try:
        full = settings.project_root / doc.file_path
        if full.exists():
            full.unlink()
    except Exception as e:
        logger.warning("Could not delete file %s: %s", doc.file_path, e)
    await db.delete(doc)
    await db.commit()
    return True


async def move_document(
    db: AsyncSession, doc_id: str, user_id: str, folder_id: str | None
) -> Document | None:
    doc = await get_document(db, doc_id, user_id)
    if doc is None:
        return None
    doc.folder_id = folder_id
    await db.commit()
    await db.refresh(doc)
    return doc


async def update_document_meta(
    db: AsyncSession,
    doc_id: str,
    user_id: str,
    title: str | None = None,
    tags: str | None = None,
    description: str | None = None,
) -> Document | None:
    doc = await get_document(db, doc_id, user_id)
    if doc is None:
        return None
    if title is not None:
        doc.title = title.strip()
    if tags is not None:
        doc.tags = tags
    if description is not None:
        doc.description = description
    await db.commit()
    await db.refresh(doc)
    return doc


def read_document_content(doc: Document) -> str:
    """Read the raw text of a stored document."""
    path = settings.project_root / doc.file_path
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


async def search_documents(
    db: AsyncSession,
    user_id: str,
    query: str,
) -> list[Document]:
    """
    Simple SQL-based search across title, filename, tags, description.
    Full-text / semantic search can be layered here later.
    """
    q_lower = f"%{query.lower()}%"
    from sqlalchemy import or_, func
    result = await db.execute(
        select(Document).where(
            Document.owner_id == user_id,
            or_(
                func.lower(Document.title).like(q_lower),
                func.lower(Document.original_filename).like(q_lower),
                func.lower(Document.tags).like(q_lower),
                func.lower(Document.description).like(q_lower),
            ),
        ).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())
