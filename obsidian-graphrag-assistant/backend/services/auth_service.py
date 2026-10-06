"""
Authentication service — registration, login, token management.
Passwords are hashed with argon2. JWTs are issued as HTTP-only cookies.
"""
import logging
from sqlalchemy.orm import Session

from backend.core.security import hash_password, verify_password, create_access_token
from backend.db.models import User
from backend.services.user_service import (
    get_user_by_email,
    get_user_by_phone,
    create_user,
)

logger = logging.getLogger(__name__)


def register_user(
    db: Session,
    name: str,
    email: str,
    phone: str,
    password: str,
) -> User:
    """Register a new user. Raises ValueError on conflicts."""
    email = email.strip().lower()
    phone = phone.strip()

    if get_user_by_email(db, email):
        raise ValueError("An account with that email already exists.")
    if get_user_by_phone(db, phone):
        raise ValueError("An account with that phone already exists.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    user = create_user(db, name=name, email=email, phone=phone, password=password)
    logger.info("Registered user: %s (id=%s)", user.email, user.id)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Verify credentials and return the User if valid."""
    user = get_user_by_email(db, email.strip().lower())
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def login_user(db: Session, email: str, password: str) -> str | None:
    """Authenticate and return a JWT string (to be set as cookie by the route)."""
    user = authenticate(db, email, password)
    if user is None:
        return None
    token = create_access_token({"sub": user.id})
    logger.info("Login token issued for user: %s", user.email)
    return token
