"""
Script: initialize_database.py
Initializes MySQL tables + Neo4j user-scoped constraints/indexes/vector index.
Safe to run multiple times. Does NOT delete existing data.
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, verify_connectivity, close_driver
from backend.services.graph_service import (
    create_constraints_and_indexes,
    create_vector_index,
    get_vector_index_status,
)

configure_logging()
logger = logging.getLogger(__name__)


def main():
    print(f"\n{'='*60}")
    print("Database Initialisation (MySQL + Neo4j)")
    print(f"{'='*60}")

    # ── MySQL ──────────────────────────────────────────────────────────────
    print("\n── MySQL ──")
    try:
        from backend.db.mysql import init_mysql, engine
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print(f"✓ MySQL connected: {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}")
            tables = conn.execute(text("SHOW TABLES")).fetchall()
            print(f"  Existing tables: {[t[0] for t in tables]}")
        init_mysql()
        with engine.connect() as conn:
            tables = conn.execute(text("SHOW TABLES")).fetchall()
            print(f"  Tables after init: {[t[0] for t in tables]}")
        print("✓ MySQL tables ensured")
    except Exception as e:
        print(f"❌ MySQL failed: {e}")
        sys.exit(1)

    # ── Neo4j ──────────────────────────────────────────────────────────────
    print("\n── Neo4j ──")
    try:
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    except Exception as e:
        print(f"❌ Neo4j driver init failed: {e}")
        sys.exit(1)

    if not verify_connectivity():
        print("❌ Neo4j connection FAILED")
        sys.exit(1)
    print(f"✓ Neo4j connected: {settings.neo4j_uri}")

    # Constraints and indexes (user-scoped)
    print("\nCreating user-scoped constraints and indexes...")
    try:
        create_constraints_and_indexes()
        print("✓ Constraints and indexes created")
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)

    # Vector index
    print(f"\nCreating vector index '{settings.vector_index_name}'...")
    print(f"  Dimensions: {settings.embedding_dimensions}")
    print(f"  Similarity: cosine")
    try:
        create_vector_index(
            index_name=settings.vector_index_name,
            dimensions=settings.embedding_dimensions,
        )
        print("✓ Vector index created")
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)

    # Verify
    status = get_vector_index_status(settings.vector_index_name)
    print(f"\nVector index status: {status}")

    close_driver()

    print(f"\n✓ Database initialisation complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
