"""
Alembic migration environment.
Reads the database URL from the app's settings (via .env) — never hardcoded.
"""
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure project root is importable
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.core.config import settings
from backend.db.mysql import Base
# Import all models so they register on Base.metadata
from backend.db.models import User, Folder, Note  # noqa: F401

config = context.config

# Override the SQLAlchemy URL — set it directly on the config object
# (bypass configparser interpolation issues with % in URL-encoded passwords)
config.config_args["sqlalchemy.url"] = settings.mysql_url

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the database)."""
    # Create engine directly from app settings — bypasses configparser
    # to avoid interpolation issues with URL-encoded passwords
    from sqlalchemy import create_engine
    connectable = create_engine(settings.mysql_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
