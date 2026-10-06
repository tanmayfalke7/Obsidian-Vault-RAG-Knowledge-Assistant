"""Note model — user-owned Markdown note stored in MySQL.

note.id is the stable identifier that connects MySQL rows to Neo4j nodes.
Every Neo4j node derived from a note (Note, Chunk, Concept) carries
the same user_id so the graph is strictly tenant-isolated.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.mysql import Base


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_user_id", "user_id"),
        Index("ix_notes_folder_id", "folder_id"),
        Index("ix_notes_updated_at", "updated_at"),
        Index("ix_notes_user_filename", "user_id", "filename"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    folder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text(length=16777215), nullable=False)  # MEDIUMTEXT
    source_type: Mapped[str] = mapped_column(String(20), default="uploaded")  # created | uploaded
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="notes")
    folder: Mapped["Folder | None"] = relationship("Folder", back_populates="notes")
