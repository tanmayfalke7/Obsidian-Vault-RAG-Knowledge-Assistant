"""
MySQL database engine, session factory, and declarative base.
Uses synchronous pymysql driver — consistent with the existing Neo4j client.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ── Engine ─────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,       # verify connection is alive before use
    pool_recycle=3600,         # recycle connections hourly
    pool_size=5,
    max_overflow=10,
    echo=False,
)

# ── Session factory ────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a synchronous MySQL session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_mysql() -> None:
    """Create all tables. Called on startup (before Alembic is wired)."""
    from backend.db.models import Base  # noqa: F811
    Base.metadata.create_all(bind=engine)
    logger.info("MySQL tables ensured (notes_db).")


# ── Declarative base ───────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass
