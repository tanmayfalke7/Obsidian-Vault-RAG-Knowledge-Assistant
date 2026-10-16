"""
Web application entry point.

Mounts the new FastAPI+HTMX web app while preserving the existing
GraphRAG JSON API (backend/main.py) under /api/v1/.

Run with:
    uvicorn app.main:app --reload --port 8080
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Ensure project root is on path so backend.* imports work ──────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.core.template_compat import patch_template_response_compat
from app.db.database import init_db
from app.services.graphrag_service import ensure_services

# Configure logging early
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
patch_template_response_compat()

# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═" * 60)
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("═" * 60)

    # 1. Create SQLite tables
    await init_db()
    logger.info("✓ SQLite database initialised")

    # 2. Seed admin user if DB is empty
    await _seed_admin()

    # 3. Initialise GraphRAG pipeline (Neo4j + embedding + LLM)
    try:
        ensure_services()
        logger.info("✓ GraphRAG services ready")
    except Exception as e:
        logger.warning("GraphRAG services failed to start: %s — chat will be unavailable.", e)

    logger.info("✓ Application ready at http://localhost:8080")
    logger.info("═" * 60)
    yield

    # Shutdown
    try:
        from backend.db.neo4j_client import close_driver
        close_driver()
        logger.info("Neo4j driver closed.")
    except Exception:
        pass


async def _seed_admin() -> None:
    """Create a default admin account on first run."""
    from app.db.database import AsyncSessionLocal
    from app.services.user_service import get_user_by_email, create_user
    async with AsyncSessionLocal() as db:
        existing = await get_user_by_email(db, "admin@company.com")
        if existing is None:
            await create_user(
                db,
                email="admin@company.com",
                username="admin",
                full_name="Administrator",
                password="admin1234",   # Change immediately in production
                is_admin=True,
            )
            logger.info("✓ Default admin created: admin@company.com / admin1234")


# ── App factory ────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url=None,       # Disable public docs on prod; re-enable for dev
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Static files
app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")),
    name="static",
)

# Templates (used by error handlers)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))

# ── Mount existing GraphRAG JSON API ──────────────────────────────────────
# The original FastAPI backend routes are mounted at /api/v1
# This preserves backward-compatible JSON endpoints for older clients.
try:
    from backend.api.routes import router as graphrag_router
    app.include_router(graphrag_router, prefix="/api/v1")
    logger.info("GraphRAG JSON API mounted at /api/v1")
except Exception as e:
    logger.warning("Could not mount GraphRAG JSON API: %s", e)

# ── Mount new web-app routes ───────────────────────────────────────────────
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.folders import router as folders_router
from app.api.search import router as search_router
from app.api.profile import router as profile_router
from app.api.admin import router as admin_router

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(folders_router)
app.include_router(search_router)
app.include_router(profile_router)
app.include_router(admin_router)


# ── Error handlers ─────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Auth redirects
    if exc.status_code in (status.HTTP_303_SEE_OTHER,):
        loc = exc.headers.get("Location", "/login") if exc.headers else "/login"
        return RedirectResponse(url=loc, status_code=302)

    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return templates.TemplateResponse(
            "404.html", {"request": request, "user": None},
            status_code=404,
        )
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return templates.TemplateResponse(
            "403.html", {"request": request, "user": None},
            status_code=403,
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "user": None, "status_code": exc.status_code,
         "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "user": None, "status_code": 500,
         "detail": "An unexpected error occurred."},
        status_code=500,
    )


# ── Health endpoint ────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    from backend.db.neo4j_client import verify_connectivity
    try:
        neo4j_ok = verify_connectivity()
    except Exception:
        neo4j_ok = False
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "neo4j": "connected" if neo4j_ok else "disconnected",
        "gemini": "configured" if (settings.gemini_api_key or settings.groq_api_key) else "missing",
        "groq": "configured" if (settings.gemini_api_key or settings.groq_api_key) else "missing",
    }
