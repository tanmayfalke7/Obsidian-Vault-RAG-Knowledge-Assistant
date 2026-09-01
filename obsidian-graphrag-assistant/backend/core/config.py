"""
Central application configuration — Groq LLM + fastembed embeddings + Neo4j.
"""
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Neo4j ──────────────────────────────────────────────────────────────
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(...)
    neo4j_database: str = Field(default="neo4j")

    # ── Groq LLM ───────────────────────────────────────────────────────────
    groq_api_key: str = Field(...)
    groq_llm_model: str = Field(default="groq/compound-mini")

    # ── Embeddings (fastembed, local, no API key) ──────────────────────────
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embedding_dimensions: int = Field(default=384)

    # ── Vector / Retrieval ─────────────────────────────────────────────────
    vector_index_name: str = Field(default="chunk_embedding_index")
    top_k: int = Field(default=5)
    graph_hops: int = Field(default=2)

    # ── Application ────────────────────────────────────────────────────────
    project_tag: str = Field(default="obsidian-graphrag-assistant")
    log_level: str = Field(default="INFO")

    @property
    def vault_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "vault"


def _build_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    env_file = project_root / ".env"
    return Settings(_env_file=str(env_file))  # type: ignore[call-arg]


settings = _build_settings()


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
