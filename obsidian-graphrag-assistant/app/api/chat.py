"""
AI Chat routes.
History is NEVER persisted — every request is stateless on the server side.
The browser may display the conversation but nothing is stored in any database.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import User, get_db
from app.services.graphrag_service import ask_graphrag
from app.services.user_service import increment_query_count

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "user": current_user,
        "can_query": current_user.can_query(),
        "query_used": current_user.ai_queries_used,
        "query_limit": current_user.max_ai_queries,
        "query_remaining": current_user.queries_remaining(),
    })


@router.post("/chat/ask", response_class=HTMLResponse)
async def chat_ask(
    request: Request,
    question: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Process one AI question.
    Returns an HTMX partial (answer card) — not a full page.
    Chat history is intentionally NOT saved anywhere.
    """
    # Verify user has remaining queries
    if not current_user.can_query():
        return templates.TemplateResponse(
            "partials/chat_limit.html",
            {"request": request, "user": current_user},
            status_code=402,
        )

    question = question.strip()
    if not question:
        return templates.TemplateResponse(
            "partials/chat_error.html",
            {"request": request, "error": "Please enter a question."},
            status_code=400,
        )

    # Increment BEFORE calling the LLM — prevents double-counting on retries
    await increment_query_count(db, current_user)

    # Run GraphRAG pipeline (synchronous — wraps existing blocking services)
    result = ask_graphrag(question)

    if result.error:
        logger.error("Chat ask error for user %s: %s", current_user.id, result.error)
        return templates.TemplateResponse(
            "partials/chat_error.html",
            {"request": request,
             "error": "The AI service encountered an error. Please try again."},
            status_code=500,
        )

    # Reload user to get updated query count
    await db.refresh(current_user)

    return templates.TemplateResponse(
        "partials/chat_answer.html",
        {
            "request": request,
            "question": question,
            "answer": result.answer,
            "sources": result.sources,
            "relationships": result.relationships,
            "chunks_used": result.chunks_used,
            "query_used": current_user.ai_queries_used,
            "query_limit": current_user.max_ai_queries,
            "query_remaining": current_user.queries_remaining(),
            "can_query": current_user.can_query(),
        },
    )
