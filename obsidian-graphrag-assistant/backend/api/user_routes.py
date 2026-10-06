"""
User routes — profile management and usage statistics.
user_id always comes from the JWT cookie. Never from the request body.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.db.mysql import get_db
from backend.db.models import User
from backend.schemas import UserResponse
from backend.services.note_service import count_notes

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's profile. Alias for /api/auth/me."""
    return UserResponse(
        id=current_user.id, name=current_user.name, email=current_user.email,
        phone=current_user.phone, is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@router.get("/me/stats")
def get_my_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return usage statistics for the authenticated user."""
    note_count = count_notes(db, current_user.id)
    return {
        "user_id": current_user.id,
        "name": current_user.name,
        "notes_count": note_count,
        "is_active": current_user.is_active,
    }
