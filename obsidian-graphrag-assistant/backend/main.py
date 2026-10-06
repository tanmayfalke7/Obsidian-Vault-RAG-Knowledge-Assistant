"""
FastAPI application entry point — multi-tenant GraphRAG backend.

Startup:
  1. Configure logging
  2. Init MySQL (create tables if missing)
  3. Init Neo4j driver + verify connectivity
  4. Init embedding service (fastembed)
  5. Init LLM service (Groq)

Routes:
  /api/auth/*     — registration, login, logout, me
  /api/notes/*    — note CRUD, upload, reindex (user-scoped)
  /api/folders/*  — folder CRUD (user-scoped)
  /api/search     — note search (user-scoped)
  /api/rag/query  — GraphRAG query (user-scoped)
  /api/v1/*       — legacy JSON API (global, for backward compatibility)
  /health         — health check
"""
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, close_driver, verify_connectivity
from backend.services.embedding_service import init_embedding_service
from backend.services.llm_service import init_llm_service

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═" * 60)
    logger.info("Starting %s — multi-tenant GraphRAG backend", settings.project_tag)
    logger.info("═" * 60)

    # 1. MySQL
    from backend.db.mysql import init_mysql
    init_mysql()
    logger.info("✓ MySQL ready (notes_db)")

    # 2. Neo4j
    try:
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
        if verify_connectivity():
            logger.info("✓ Neo4j connected: %s", settings.neo4j_uri)
        else:
            logger.warning("⚠️ Neo4j connectivity check failed")
    except Exception as e:
        logger.warning("⚠️ Neo4j init failed: %s — graph features unavailable", e)

    # 3. Embeddings (fastembed, local)
    try:
        init_embedding_service(settings.embedding_model)
        logger.info("✓ Embedding service: %s (%d dims)", settings.embedding_model, settings.embedding_dimensions)
    except Exception as e:
        logger.warning("⚠️ Embedding service init failed: %s", e)

    # 4. LLM (Groq)
    try:
        init_llm_service(settings.groq_api_key, settings.groq_llm_model)
        logger.info("✓ LLM service (Groq): %s", settings.groq_llm_model)
    except Exception as e:
        logger.warning("⚠️ LLM service init failed: %s", e)

    logger.info("═" * 60)
    logger.info("Application ready at http://localhost:8000")
    logger.info("API docs at http://localhost:8000/docs")
    logger.info("═" * 60)
    yield

    # Shutdown
    close_driver()
    logger.info("Neo4j driver closed. Goodbye.")


app = FastAPI(
    title="GraphRAG Knowledge Assistant API",
    description="Multi-tenant GraphRAG backend with MySQL + Neo4j + Groq",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_static = Path(__file__).resolve().parents[1] / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(frontend_static)), name="static")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled backend error at %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# ── Mount new multi-tenant routes ──────────────────────────────────────────
from backend.api.auth_routes import router as auth_router
from backend.api.note_routes import router as note_router
from backend.api.folder_routes import router as folder_router
from backend.api.search_routes import router as search_router
from backend.api.rag_routes import router as rag_router
from backend.api.user_routes import router as user_router
from backend.api.graph_routes import router as graph_router
from backend.api.frontend_routes import router as frontend_router

app.include_router(auth_router)
app.include_router(note_router)
app.include_router(folder_router)
app.include_router(search_router)
app.include_router(rag_router)
app.include_router(user_router)
app.include_router(graph_router)
app.include_router(frontend_router)

# ── Mount legacy routes (global JSON API, for backward compatibility) ────
from backend.api.routes import router as legacy_router
app.include_router(legacy_router, prefix="/api/v1")


# ── Health ─────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health():
    from backend.schemas import HealthResponse
    neo4j_ok = verify_connectivity()
    return HealthResponse(
        status="ok" if neo4j_ok else "degraded",
        mysql="connected",  # tables already created on startup
        neo4j="connected" if neo4j_ok else "disconnected",
        groq="configured" if settings.groq_api_key else "missing",
    )
