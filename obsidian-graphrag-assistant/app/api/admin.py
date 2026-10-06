"""Admin routes: dashboard, user management, access requests."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.db.database import User, get_db
from app.services.graphrag_service import get_graph_stats
from app.services.user_service import (
    get_all_users,
    get_pending_access_requests,
    resolve_access_request,
    update_user_limits,
    get_user_by_id,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = await get_all_users(db)
    pending = await get_pending_access_requests(db)
    stats = get_graph_stats()

    total_docs = sum(len(u.documents) for u in users)
    total_queries = sum(u.ai_queries_used for u in users)

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": admin,
        "users": users,
        "pending_count": len(pending),
        "total_docs": total_docs,
        "total_queries": total_queries,
        "graph_stats": stats,
        "user_count": len(users),
    })


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = await get_all_users(db)
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": admin,
        "users": users,
    })


@router.post("/users/{user_id}/limits", response_class=HTMLResponse)
async def admin_update_limits(
    request: Request,
    user_id: str,
    max_documents: int = Form(...),
    max_ai_queries: int = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await get_user_by_id(db, user_id)
    if target:
        await update_user_limits(db, target, max_documents, max_ai_queries)
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content='<span class="badge badge-success">Updated</span>',
            status_code=200,
        )
    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/{user_id}/toggle", response_class=HTMLResponse)
async def admin_toggle_user(
    request: Request,
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await get_user_by_id(db, user_id)
    if target and target.id != admin.id:
        target.is_active = not target.is_active
        await db.commit()
    if request.headers.get("HX-Request"):
        status_text = "Active" if (target and target.is_active) else "Inactive"
        cls = "badge-success" if (target and target.is_active) else "badge-error"
        return HTMLResponse(
            content=f'<span class="badge {cls}">{status_text}</span>',
            status_code=200,
        )
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/requests", response_class=HTMLResponse)
async def admin_requests(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    pending = await get_pending_access_requests(db)
    return templates.TemplateResponse("admin/requests.html", {
        "request": request,
        "user": admin,
        "requests": pending,
    })


@router.post("/requests/{request_id}/approve", response_class=HTMLResponse)
async def admin_approve(
    request: Request,
    request_id: str,
    admin_note: str = Form(default=""),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await resolve_access_request(
        db, request_id, "approved", admin_note or None, admin.id
    )
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content='<span class="badge badge-success">Approved</span>',
            status_code=200,
        )
    return RedirectResponse(url="/admin/requests", status_code=302)


@router.post("/requests/{request_id}/reject", response_class=HTMLResponse)
async def admin_reject(
    request: Request,
    request_id: str,
    admin_note: str = Form(default=""),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await resolve_access_request(
        db, request_id, "rejected", admin_note or None, admin.id
    )
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content='<span class="badge badge-error">Rejected</span>',
            status_code=200,
        )
    return RedirectResponse(url="/admin/requests", status_code=302)
