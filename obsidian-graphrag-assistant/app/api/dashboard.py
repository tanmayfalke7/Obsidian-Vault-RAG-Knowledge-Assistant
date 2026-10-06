"""Dashboard route."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.document_service import get_all_documents_for_user
from app.services.folder_service import get_folders_for_user

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    documents = await get_all_documents_for_user(db, current_user.id)
    folders = await get_folders_for_user(db, current_user.id)

    recent_docs = sorted(documents, key=lambda d: d.created_at, reverse=True)[:5]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "documents": documents,
        "folders": folders,
        "recent_docs": recent_docs,
        "doc_count": len(documents),
        "doc_limit": current_user.max_documents,
        "doc_remaining": max(0, current_user.max_documents - len(documents)),
        "query_used": current_user.ai_queries_used,
        "query_limit": current_user.max_ai_queries,
        "query_remaining": current_user.queries_remaining(),
        "can_query": current_user.can_query(),
        "can_upload": current_user.can_upload(),
    })
