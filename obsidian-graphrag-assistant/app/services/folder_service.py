"""Folder CRUD operations."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import Folder, Document


async def get_folders_for_user(db: AsyncSession, user_id: str) -> list[Folder]:
    result = await db.execute(
        select(Folder)
        .options(selectinload(Folder.documents))
        .where(Folder.owner_id == user_id)
        .order_by(Folder.name)
    )
    return list(result.scalars().all())


async def get_folder(db: AsyncSession, folder_id: str, user_id: str) -> Folder | None:
    result = await db.execute(
        select(Folder)
        .options(selectinload(Folder.documents))
        .where(Folder.id == folder_id, Folder.owner_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_folder(
    db: AsyncSession, name: str, user_id: str, description: str | None = None
) -> Folder:
    folder = Folder(name=name.strip(), owner_id=user_id, description=description)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def rename_folder(
    db: AsyncSession, folder_id: str, user_id: str, new_name: str
) -> Folder | None:
    folder = await get_folder(db, folder_id, user_id)
    if folder is None:
        return None
    folder.name = new_name.strip()
    await db.commit()
    await db.refresh(folder)
    return folder


async def delete_folder(db: AsyncSession, folder_id: str, user_id: str) -> bool:
    folder = await get_folder(db, folder_id, user_id)
    if folder is None:
        return False
    # Unlink documents before deleting
    result = await db.execute(
        select(Document).where(Document.folder_id == folder_id)
    )
    for doc in result.scalars().all():
        doc.folder_id = None
    await db.delete(folder)
    await db.commit()
    return True
