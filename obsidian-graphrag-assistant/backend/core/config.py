"""
Central application configuration — Groq LLM + fastembed embeddings + Neo4j + MySQL.
Reads from .env. All secrets stay here — never exposed via API or logs.
"""
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


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

    # ── MySQL ───────────────────────────────────────────────────────────────
    mysql_host: str = Field(default="localhost")
    mysql_port: int = Field(default=3306)
    mysql_database: str = Field(default="notes_db")
    mysql_username: str = Field(default="root")
    mysql_password: str = Field(...)

    # ── JWT / Auth ──────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(...)
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=480)
    auth_cookie_name: str = Field(default="access_token")
    auth_cookie_secure: bool | None = Field(default=None)
    auth_cookie_samesite: Literal["lax", "strict", "none"] = Field(default="lax")
    auth_cookie_domain: str | None = Field(default=None)

    # ── Groq LLM ───────────────────────────────────────────────────────────
    groq_api_key: str = Field(...)
    groq_llm_model: str = Field(default="groq/compound-mini")

    # ── Embeddings (fastembed, local, no API key) ──────────────────────────
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    embedding_dimensions: int = Field(default=384)

    # ── Vector / Retrieval ─────────────────────────────────────────────────
    vector_index_name: str = Field(default="chunk_embedding_index")
    top_k: int = Field(default=5)
    graph_hops: int = Field(default=2)
    graph_max_nodes: int = Field(default=100)
    graph_max_depth: int = Field(default=2)

    # ── Application ────────────────────────────────────────────────────────
    project_tag: str = Field(default="obsidian-graphrag-assistant")
    environment: Literal["development", "test", "production"] = Field(default="development")
    frontend_origin: str = Field(default="http://localhost:8000")
    frontend_origins: str = Field(default="")
    log_level: str = Field(default="INFO")
    max_markdown_file_size_mb: int = Field(default=10)

    # ── Abuse protection ───────────────────────────────────────────────────
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_login_per_minute: int = Field(default=120)
    rate_limit_register_per_hour: int = Field(default=60)
    rate_limit_expensive_per_minute: int = Field(default=60)

    @property
    def mysql_url(self) -> str:
        """SQLAlchemy URL for MySQL via pymysql. Password is URL-encoded."""
        from urllib.parse import quote_plus
        pwd = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{self.mysql_username}:{pwd}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def vault_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "vault"

    @property
    def cors_origins(self) -> list[str]:
        configured = self.frontend_origins or self.frontend_origin
        origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
        return origins or ["http://localhost:8000"]

    @property
    def cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.environment == "production"


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
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
