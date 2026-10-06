"""Folder management routes."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.document_service import get_documents_for_user
from app.services.folder_service import (
    create_folder, delete_folder, get_folder,
    get_folders_for_user, rename_folder,
)

router = APIRouter(prefix="/folders", tags=["folders"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def folders_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folders = await get_folders_for_user(db, current_user.id)
    return templates.TemplateResponse("folders.html", {
        "request": request,
        "user": current_user,
        "folders": folders,
    })


@router.post("/create", response_class=HTMLResponse)
async def folder_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await create_folder(db, name, current_user.id, description or None)
    if request.headers.get("HX-Request"):
        folders = await get_folders_for_user(db, current_user.id)
        return templates.TemplateResponse("partials/folder_list.html", {
            "request": request,
            "user": current_user,
            "folders": folders,
        })
    return RedirectResponse(url=f"/folders/{folder.id}", status_code=302)


@router.get("/{folder_id}", response_class=HTMLResponse)
async def folder_view(
    request: Request,
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id, current_user.id)
    if folder is None:
        return templates.TemplateResponse("404.html", {
            "request": request, "user": current_user,
        }, status_code=404)

    documents = await get_documents_for_user(db, current_user.id, folder_id=folder_id)
    all_folders = await get_folders_for_user(db, current_user.id)

    return templates.TemplateResponse("folder.html", {
        "request": request,
        "user": current_user,
        "folder": folder,
        "documents": documents,
        "all_folders": all_folders,
    })


@router.post("/{folder_id}/rename", response_class=HTMLResponse)
async def folder_rename(
    request: Request,
    folder_id: str,
    name: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await rename_folder(db, folder_id, current_user.id, name)
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content=f'<span class="folder-name">{folder.name if folder else name}</span>',
            status_code=200,
        )
    return RedirectResponse(url=f"/folders/{folder_id}", status_code=302)


@router.post("/{folder_id}/delete", response_class=HTMLResponse)
async def folder_delete(
    request: Request,
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_folder(db, folder_id, current_user.id)
    if request.headers.get("HX-Request"):
        return HTMLResponse(content="", status_code=200)
    return RedirectResponse(url="/folders", status_code=302)
