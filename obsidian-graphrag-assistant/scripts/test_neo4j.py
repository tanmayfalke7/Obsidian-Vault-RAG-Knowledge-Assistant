"""
Script: test_neo4j.py
Tests Neo4j connectivity and prints basic database info.
"""
import sys
import logging
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, verify_connectivity, run_query, close_driver

configure_logging()
logger = logging.getLogger(__name__)


def main():
    print(f"\n{'='*60}")
    print("Neo4j Connectivity Test")
    print(f"{'='*60}")
    print(f"URI:      {settings.neo4j_uri}")
    print(f"Username: {settings.neo4j_username}")
    print(f"Database: {settings.neo4j_database}")
    print()

    try:
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    except Exception as e:
        print(f"❌ Failed to create driver: {e}")
        sys.exit(1)

    ok = verify_connectivity()
    if not ok:
        print("❌ Neo4j connection FAILED")
        sys.exit(1)

    print("✓ Neo4j connection OK")

    # Basic stats
    try:
        results = run_query("MATCH (n) RETURN labels(n) AS labels, count(n) AS cnt ORDER BY cnt DESC LIMIT 10",
                            database=settings.neo4j_database)
        print("\nDatabase node counts:")
        for row in results:
            print(f"  {row['labels']}: {row['cnt']}")

        # Check for project nodes
        proj_results = run_query(
            "MATCH (n {project: $project}) RETURN labels(n) AS labels, count(n) AS cnt",
            {"project": settings.project_tag},
            database=settings.neo4j_database,
        )
        print(f"\nProject '{settings.project_tag}' nodes:")
        if proj_results:
            for row in proj_results:
                print(f"  {row['labels']}: {row['cnt']}")
        else:
            print("  (none — database not yet ingested)")

    except Exception as e:
        print(f"Warning: Could not run stats query: {e}")

    close_driver()
    print("\n✓ Test complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
