"""
Script: ingest_vault.py
Parses the Obsidian vault and populates Neo4j with nodes, relationships, and embeddings.
"""
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, verify_connectivity, close_driver
from backend.services.embedding_service import init_embedding_service
from backend.services.ingestion_service import run_ingestion

configure_logging()
logger = logging.getLogger(__name__)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ingest Obsidian vault into Neo4j")
    parser.add_argument("--vault", default=None, help="Path to vault directory")
    parser.add_argument("--reset", action="store_true",
                        help="Delete existing project data before ingesting")
    args = parser.parse_args()

    vault_path = Path(args.vault) if args.vault else settings.vault_path

    print(f"\n{'='*60}")
    print("Obsidian Vault Ingestion")
    print(f"{'='*60}")
    print(f"Vault:    {vault_path}")
    print(f"Reset:    {args.reset}")
    print()

    if not vault_path.exists():
        print(f"❌ Vault path does not exist: {vault_path}")
        sys.exit(1)

    # Initialise services
    try:
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    except Exception as e:
        print(f"❌ Neo4j driver init failed: {e}")
        sys.exit(1)

    if not verify_connectivity():
        print("❌ Neo4j connection FAILED")
        sys.exit(1)
    print("✓ Neo4j connected")

    init_embedding_service(settings.embedding_model)
    print(f"✓ Embedding service: {settings.embedding_model}")
    print()

    # Run ingestion
    start = time.time()
    stats = run_ingestion(vault_path, reset=args.reset)
    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print("Ingestion Complete")
    print(f"{'='*60}")
    print(f"Notes processed:      {stats.notes_processed}")
    print(f"Chunks created:       {stats.chunks_created}")
    print(f"Concepts created:     {stats.concepts_created}")
    print(f"Relationships created:{stats.relationships_created}")
    print(f"Embeddings generated: {stats.embeddings_generated}")
    print(f"Errors:               {len(stats.errors)}")
    print(f"Time elapsed:         {elapsed:.1f}s")

    if stats.errors:
        print(f"\nErrors encountered:")
        for err in stats.errors:
            print(f"  ⚠️  {err}")

    close_driver()
    print(f"\n{'='*60}\n")

    if stats.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
