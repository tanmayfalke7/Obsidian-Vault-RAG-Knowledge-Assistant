"""
FastAPI application entry point.

Startup:
  1. Configure logging
  2. Initialise Neo4j driver
  3. Initialise Gemini embedding service
  4. Initialise Gemini LLM service
  5. Verify Neo4j connectivity

Shutdown:
  Close Neo4j driver
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, close_driver, verify_connectivity
from backend.services import embedding_service, llm_service
from backend.api.routes import router

configure_logging()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Obsidian GraphRAG Knowledge Assistant",
        description=(
            "A GraphRAG-powered knowledge assistant that combines "
            "Neo4j vector search with knowledge graph traversal and Gemini generation."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Allow Streamlit (any origin in dev; restrict in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(router)

    @app.on_event("startup")
    async def startup_event():
        logger.info("═" * 60)
        logger.info("Starting Obsidian GraphRAG Knowledge Assistant")
        logger.info("═" * 60)

        # Neo4j
        init_driver(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
        )
        ok = verify_connectivity()
        if not ok:
            logger.error("⚠️  Neo4j connection FAILED. Check NEO4J_* env vars.")
        else:
            logger.info("✓ Neo4j connected: %s", settings.neo4j_uri)

        # Embedding service (fastembed, local)
        embedding_service.init_embedding_service(model_name=settings.embedding_model)
        logger.info("✓ Embedding service: %s (%d dims)", settings.embedding_model, settings.embedding_dimensions)

        # Groq LLM service
        llm_service.init_llm_service(
            api_key=settings.groq_api_key,
            model=settings.groq_llm_model,
        )
        logger.info("✓ LLM service (Groq): %s", settings.groq_llm_model)
        logger.info("═" * 60)

    @app.on_event("shutdown")
    async def shutdown_event():
        close_driver()
        logger.info("Neo4j driver closed. Goodbye.")

    return app


app = create_app()
