"""
Web application configuration.
Reads from the same .env file as the existing GraphRAG backend.
All business limits are centralised here — never hard-coded elsewhere.
"""
import secrets
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Neo4j (passed through to existing GraphRAG services) ───────────────
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(...)
    neo4j_database: str = Field(default="neo4j")

    # ── LLM / Embeddings ──────────────────────────────────────────────────
    gemini_api_key: str = Field(default="")
    gemini_llm_model: str = Field(default="gemini-3.8-flash")
    groq_api_key: str = Field(default="")
    groq_llm_model: str = Field(default="groq/compound-mini")

    @property
    def llm_api_key(self) -> str:
        return self.gemini_api_key or self.groq_api_key

    @property
    def llm_model(self) -> str:
        return self.gemini_llm_model or "gemini-3.8-flash"
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embedding_dimensions: int = Field(default=384)
    vector_index_name: str = Field(default="chunk_embedding_index")
    top_k: int = Field(default=5)
    graph_hops: int = Field(default=2)
    project_tag: str = Field(default="obsidian-graphrag-assistant")

    # ── Web-app auth ───────────────────────────────────────────────────────
    secret_key: str = Field(
        default_factory=lambda: secrets.token_hex(32),
        description="JWT signing secret – set WEB_SECRET_KEY in .env for production",
    )
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=480)   # 8 hours

    # ── Storage ────────────────────────────────────────────────────────────
    database_url: str = Field(default="sqlite+aiosqlite:///./app.db")
    upload_dir: str = Field(default="uploads")              # relative to project root
    max_upload_size_mb: int = Field(default=10)

    # ── Business limits (admin-configurable later) ─────────────────────────
    max_documents_per_user: int = Field(default=10)
    max_ai_queries_per_user: int = Field(default=2)

    # ── App meta ───────────────────────────────────────────────────────────
    app_name: str = Field(default="KnowledgeBase AI")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def upload_path(self) -> Path:
        p = self.project_root / self.upload_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def vault_path(self) -> Path:
        return self.project_root / "data" / "vault"


def _load_settings() -> AppSettings:
    root = Path(__file__).resolve().parents[1]
    return AppSettings(_env_file=str(root / ".env"))  # type: ignore[call-arg]


settings = _load_settings()
