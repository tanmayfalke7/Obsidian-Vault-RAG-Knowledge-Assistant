"""Document search routes — separate from AI chat."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.document_service import search_documents

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = Query(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    results = []
    if q.strip():
        results = await search_documents(db, current_user.id, q.strip())

    # HTMX partial — only return results list
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/search_results.html", {
            "request": request,
            "results": results,
            "query": q,
        })

    return templates.TemplateResponse("search.html", {
        "request": request,
        "user": current_user,
        "results": results,
        "query": q,
    })
