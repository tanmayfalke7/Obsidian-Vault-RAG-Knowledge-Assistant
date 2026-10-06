"""Profile / account management and access request routes."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.user_service import (
    create_access_request,
    update_profile,
)

router = APIRouter(tags=["profile"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": current_user,
        "success": None,
        "error": None,
    })


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    full_name: str = Form(...),
    new_password: str = Form(default=""),
    confirm_password: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if new_password and new_password != confirm_password:
        return templates.TemplateResponse("profile.html", {
            "request": request, "user": current_user,
            "error": "Passwords do not match.", "success": None,
        }, status_code=400)

    await update_profile(
        db, current_user,
        full_name=full_name,
        new_password=new_password or None,
    )
    await db.refresh(current_user)
    return templates.TemplateResponse("profile.html", {
        "request": request, "user": current_user,
        "success": "Profile updated successfully.", "error": None,
    })


@router.get("/access-request", response_class=HTMLResponse)
async def access_request_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("access_request.html", {
        "request": request,
        "user": current_user,
        "success": None,
        "error": None,
    })


@router.post("/access-request", response_class=HTMLResponse)
async def access_request_submit(
    request: Request,
    request_type: str = Form(...),
    requested_amount: int = Form(...),
    reason: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if requested_amount < 1 or requested_amount > 100:
        return templates.TemplateResponse("access_request.html", {
            "request": request, "user": current_user,
            "error": "Requested amount must be between 1 and 100.",
            "success": None,
        }, status_code=400)

    await create_access_request(
        db, current_user, request_type, requested_amount, reason or None
    )
    return templates.TemplateResponse("access_request.html", {
        "request": request, "user": current_user,
        "success": "Your request has been submitted. An admin will review it shortly.",
        "error": None,
    })
