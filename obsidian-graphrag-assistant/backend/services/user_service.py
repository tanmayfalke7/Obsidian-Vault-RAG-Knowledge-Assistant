"""
User service — CRUD operations for users in MySQL.
"""
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.db.models import User

logger = logging.getLogger(__name__)


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()


def get_user_by_phone(db: Session, phone: str) -> User | None:
    return db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()


def create_user(
    db: Session,
    name: str,
    email: str,
    phone: str,
    password: str,
) -> User:
    """Create a new user with hashed password."""
    user = User(
        name=name.strip(),
        email=email.strip().lower(),
        phone=phone.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_with_notes(db: Session, user_id: str) -> User | None:
    """Load user with notes eagerly loaded."""
    from sqlalchemy.orm import selectinload
    result = db.execute(
        select(User)
        .options(selectinload(User.notes), selectinload(User.folders))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


def count_user_notes(db: Session, user_id: str) -> int:
    from backend.db.models import Note
    from sqlalchemy import func
    result = db.execute(
        select(func.count(Note.id)).where(Note.user_id == user_id)
    )
    return result.scalar() or 0
