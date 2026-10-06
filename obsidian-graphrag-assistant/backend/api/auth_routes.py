"""
Authentication routes: register, login, logout, me.
JWT is stored in an HTTP-only cookie. Never in localStorage.
No user_id is accepted from the client — identity comes only from the cookie.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.rate_limit import login_rate_limit, register_rate_limit
from backend.db.mysql import get_db
from backend.db.models import User
from backend.core.dependencies import get_current_user
from backend.services.auth_service import register_user, login_user
from backend.schemas import (
    RegisterRequest, LoginRequest, UserResponse, AuthMessageResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(
    req: RegisterRequest,
    _: None = Depends(register_rate_limit),
    db: Session = Depends(get_db),
):
    """Register a new user account."""
    try:
        user = register_user(db, req.name, req.email, req.phone, req.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return UserResponse(
        id=user.id, name=user.name, email=user.email,
        phone=user.phone, is_active=user.is_active, created_at=user.created_at,
    )


@router.post("/login", response_model=AuthMessageResponse)
def login(
    req: LoginRequest,
    response: Response,
    _: None = Depends(login_rate_limit),
    db: Session = Depends(get_db),
):
    """Authenticate and set an HTTP-only JWT cookie."""
    token = login_user(db, req.email, req.password)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        secure=settings.cookie_secure,
        domain=settings.auth_cookie_domain,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return AuthMessageResponse(detail="Logged in")


@router.post("/logout")
def logout(response: Response):
    """Clear the authentication cookie."""
    response.delete_cookie(
        settings.auth_cookie_name,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        secure=settings.cookie_secure,
        domain=settings.auth_cookie_domain,
    )
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserResponse(
        id=current_user.id, name=current_user.name, email=current_user.email,
        phone=current_user.phone, is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
