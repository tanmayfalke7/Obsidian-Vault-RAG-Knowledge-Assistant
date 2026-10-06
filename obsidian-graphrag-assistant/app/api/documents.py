"""Document management routes: list, upload, view, delete, move."""
import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.document_service import (
    delete_document,
    get_all_documents_for_user,
    get_document,
    move_document,
    read_document_content,
    save_upload,
    update_document_meta,
)
from app.services.folder_service import get_folders_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def documents_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    documents = await get_all_documents_for_user(db, current_user.id)
    folders = await get_folders_for_user(db, current_user.id)
    return templates.TemplateResponse("documents.html", {
        "request": request,
        "user": current_user,
        "documents": documents,
        "folders": folders,
        "doc_count": len(documents),
        "doc_limit": current_user.max_documents,
        "can_upload": current_user.can_upload(),
    })


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_upload():
        return templates.TemplateResponse("documents.html", {
            "request": request,
            "user": current_user,
            "documents": await get_all_documents_for_user(db, current_user.id),
            "folders": await get_folders_for_user(db, current_user.id),
            "error": f"You have reached your document limit ({current_user.max_documents}).",
            "doc_count": len(await get_all_documents_for_user(db, current_user.id)),
            "doc_limit": current_user.max_documents,
            "can_upload": False,
        }, status_code=400)

    folders = await get_folders_for_user(db, current_user.id)
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "user": current_user,
        "folders": folders,
        "max_size_mb": settings.max_upload_size_mb,
        "error": None,
    })


@router.post("/upload", response_class=HTMLResponse)
async def upload_submit(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    description: str = Form(default=""),
    folder_id: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_upload():
        return templates.TemplateResponse("upload.html", {
            "request": request, "user": current_user, "folders": [],
            "error": "Document limit reached.",
            "max_size_mb": settings.max_upload_size_mb,
        }, status_code=400)

    # File size guard
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        await file.seek(0)
        return templates.TemplateResponse("upload.html", {
            "request": request, "user": current_user,
            "folders": await get_folders_for_user(db, current_user.id),
            "error": f"File exceeds {settings.max_upload_size_mb} MB limit.",
            "max_size_mb": settings.max_upload_size_mb,
        }, status_code=400)

    # Re-attach content so save_upload can read it
    from io import BytesIO
    file.file = BytesIO(content)
    file.size = len(content)

    try:
        doc = await save_upload(
            db, file, current_user,
            title=title or None,
            tags=tags or None,
            description=description or None,
            folder_id=folder_id or None,
        )
        return RedirectResponse(
            url=f"/documents/{doc.id}",
            status_code=302,
        )
    except Exception as e:
        logger.error("Upload failed: %s", e)
        return templates.TemplateResponse("upload.html", {
            "request": request, "user": current_user,
            "folders": await get_folders_for_user(db, current_user.id),
            "error": "Upload failed. Please try again.",
            "max_size_mb": settings.max_upload_size_mb,
        }, status_code=500)


@router.get("/{doc_id}", response_class=HTMLResponse)
async def document_detail(
    request: Request,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await get_document(db, doc_id, current_user.id)
    if doc is None:
        return templates.TemplateResponse("404.html", {
            "request": request, "user": current_user,
        }, status_code=404)

    content = read_document_content(doc)
    folders = await get_folders_for_user(db, current_user.id)
    return templates.TemplateResponse("document.html", {
        "request": request,
        "user": current_user,
        "doc": doc,
        "content": content,
        "folders": folders,
    })


@router.post("/{doc_id}/delete", response_class=HTMLResponse)
async def document_delete(
    request: Request,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_document(db, doc_id, current_user.id)
    if request.headers.get("HX-Request"):
        # Return empty 200 — HTMX will remove the element
        return HTMLResponse(content="", status_code=200)
    return RedirectResponse(url="/documents", status_code=302)


@router.post("/{doc_id}/move", response_class=HTMLResponse)
async def document_move(
    request: Request,
    doc_id: str,
    folder_id: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await move_document(db, doc_id, current_user.id, folder_id or None)
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content='<span class="badge badge-success">Moved</span>',
            status_code=200,
        )
    return RedirectResponse(url=f"/documents/{doc_id}", status_code=302)


@router.post("/{doc_id}/edit", response_class=HTMLResponse)
async def document_edit(
    request: Request,
    doc_id: str,
    title: str = Form(...),
    tags: str = Form(default=""),
    description: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await update_document_meta(
        db, doc_id, current_user.id,
        title=title, tags=tags or None, description=description or None,
    )
    return RedirectResponse(url=f"/documents/{doc_id}", status_code=302)
