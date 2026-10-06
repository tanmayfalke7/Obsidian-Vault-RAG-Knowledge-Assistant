"""
Search routes — ranked full-text search over the authenticated user's notes.
The SQL query itself always contains the user_id constraint.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.db.mysql import get_db
from backend.db.models import User
from backend.services.note_service import search_notes
from backend.schemas import NoteSearchResult, SearchResponse

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Search the authenticated user's notes.

    Covers: title, filename, content.
    Results are ranked: title match > filename match > content match.
    Each result includes a snippet showing where the match occurred.

    This endpoint never searches other users' notes — the SQL query
    includes user_id as a WHERE condition.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Search query is required")

    raw_results = search_notes(db, current_user.id, query, limit=limit)

    return SearchResponse(
        query=query,
        results=[
            NoteSearchResult(
                id=r["id"],
                title=r["title"],
                filename=r["filename"],
                folder_id=r["folder_id"],
                snippet=r.get("snippet"),
                match_field=r.get("match_field", "content"),
                updated_at=r["updated_at"],
            )
            for r in raw_results
        ],
        total=len(raw_results),
    )
