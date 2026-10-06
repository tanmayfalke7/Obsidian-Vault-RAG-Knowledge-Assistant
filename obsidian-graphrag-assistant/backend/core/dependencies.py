"""
FastAPI dependency injectors.

CRITICAL: The current user identity comes ONLY from the validated JWT cookie.
The frontend NEVER sends user_id in any request body or parameter.
No endpoint accepts user_id from the client.
"""
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.security import decode_access_token
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services.user_service import get_user_by_id


# ── Auth dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Read JWT from 'access_token' HTTP-only cookie and return the User.

    This is the ONLY way user identity is established. No endpoint
    accepts a user_id parameter from the request.
    """
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def get_current_user_sync(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Synchronous version for non-async route handlers."""
    return await get_current_user(request, db)


async def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Return user if authenticated, None otherwise (for public endpoints)."""
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        return None
    return user
