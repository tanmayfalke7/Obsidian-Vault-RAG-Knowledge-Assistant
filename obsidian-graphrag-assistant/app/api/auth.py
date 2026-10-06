"""
Authentication routes: login, register, logout.
Supports both full-page and HTMX partial responses.
"""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token
from app.db.database import get_db
from app.services.user_service import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_username,
)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


# ── Landing / Login ────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "app_name": settings.app_name,
        "error": None,
    })


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, email, password)
    if user is None:
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "partials/auth_error.html",
                {"request": request, "error": "Invalid email or password."},
                status_code=400,
            )
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "app_name": settings.app_name,
             "error": "Invalid email or password."},
            status_code=400,
        )

    token = create_access_token({"sub": user.id})
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,          # Set True in production with HTTPS
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


# ── Register ───────────────────────────────────────────────────────────────

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {
        "request": request,
        "app_name": settings.app_name,
        "error": None,
    })


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ctx = {"request": request, "app_name": settings.app_name}

    # Validation
    if password != password_confirm:
        ctx["error"] = "Passwords do not match."
        return templates.TemplateResponse("register.html", ctx, status_code=400)

    if len(password) < 8:
        ctx["error"] = "Password must be at least 8 characters."
        return templates.TemplateResponse("register.html", ctx, status_code=400)

    if await get_user_by_email(db, email):
        ctx["error"] = "An account with that email already exists."
        return templates.TemplateResponse("register.html", ctx, status_code=400)

    if await get_user_by_username(db, username):
        ctx["error"] = "That username is already taken."
        return templates.TemplateResponse("register.html", ctx, status_code=400)

    user = await create_user(db, email, username, full_name, password)
    token = create_access_token({"sub": user.id})

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


# ── Logout ─────────────────────────────────────────────────────────────────

@router.get("/logout")
@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response
