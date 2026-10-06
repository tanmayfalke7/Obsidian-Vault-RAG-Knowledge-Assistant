"""Jinja frontend routes for the production GraphRAG web UI."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.core.dependencies import get_optional_user
from backend.db.models import User
from backend.db.mysql import get_db
from backend.services.folder_service import get_all_folders_for_user
from backend.services.graph_service import get_graph_stats
from backend.services.note_service import get_notes_paginated, count_notes

templates = Jinja2Templates(directory="frontend/templates")
router = APIRouter(tags=["frontend"])


def _active_context(request: Request, active_page: str, user: User | None = None) -> dict:
    return {
        "request": request,
        "active_page": active_page,
        "user": user,
        "app_name": "Vault GraphRAG",
    }


@router.get("/", include_in_schema=False)
def root(user: User | None = Depends(get_optional_user)):
    return RedirectResponse("/dashboard" if user else "/login", status_code=302)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/login.html", _active_context(request, "login"))


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/register.html", _active_context(request, "register"))


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    recent_created = get_notes_paginated(
        db, current_user.id, include_all=True, sort="created_at", order="desc", page=1, page_size=5
    )["items"]
    recent_updated = get_notes_paginated(
        db, current_user.id, include_all=True, sort="updated_at", order="desc", page=1, page_size=5
    )["items"]
    folders = get_all_folders_for_user(db, current_user.id)
    try:
        graph_stats = get_graph_stats(current_user.id)
    except Exception:
        graph_stats = {"concepts": 0, "rels": 0}

    ctx = _active_context(request, "dashboard", current_user)
    ctx.update({
        "note_count": count_notes(db, current_user.id),
        "folder_count": len(folders),
        "entity_count": graph_stats.get("concepts", 0),
        "triple_count": graph_stats.get("rels", 0),
        "last_sync": datetime.now(timezone.utc),
        "recent_created": recent_created,
        "recent_updated": recent_updated,
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/notes", response_class=HTMLResponse, include_in_schema=False)
def notes_page(
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    folders = get_all_folders_for_user(db, current_user.id)
    ctx = _active_context(request, "notes", current_user)
    ctx.update({"folders": folders, "initial_note_id": request.query_params.get("note", "")})
    return templates.TemplateResponse(request, "notes/index.html", ctx)


@router.get("/notes/{note_id}", response_class=HTMLResponse, include_in_schema=False)
def note_detail_page(
    note_id: str,
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    folders = get_all_folders_for_user(db, current_user.id)
    ctx = _active_context(request, "notes", current_user)
    ctx.update({"folders": folders, "initial_note_id": note_id})
    return templates.TemplateResponse(request, "notes/index.html", ctx)


@router.get("/graph", response_class=HTMLResponse, include_in_schema=False)
def graph_page(
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    notes = get_notes_paginated(db, current_user.id, include_all=True, page=1, page_size=100)["items"]
    ctx = _active_context(request, "graph", current_user)
    ctx.update({"notes": notes})
    return templates.TemplateResponse(request, "graph/explorer.html", ctx)


@router.get("/rag", response_class=HTMLResponse, include_in_schema=False)
def rag_page(request: Request, current_user: User | None = Depends(get_optional_user)):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "rag/query.html", _active_context(request, "rag", current_user))


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(request: Request, current_user: User | None = Depends(get_optional_user)):
    if current_user is None:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "settings.html", _active_context(request, "settings", current_user))
