"""
Script: create_indexes.py
Explicitly creates or verifies all Neo4j indexes and constraints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, run_query, close_driver, verify_connectivity
from backend.services.graph_service import get_vector_index_status

configure_logging()


def main():
    print(f"\n{'='*60}")
    print("Index and Constraint Verification")
    print(f"{'='*60}")

    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    if not verify_connectivity():
        print("❌ Neo4j connection FAILED")
        sys.exit(1)

    # List all indexes
    indexes = run_query("SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties",
                        database=settings.neo4j_database)
    print(f"\nAll indexes ({len(indexes)} total):")
    for idx in indexes:
        print(f"  [{idx.get('state','?'):8}] {idx.get('type','?'):12} {idx.get('name','?')}")
        print(f"           Labels: {idx.get('labelsOrTypes',[])}  Props: {idx.get('properties',[])}")

    # Vector index specifically
    vstatus = get_vector_index_status(settings.vector_index_name)
    print(f"\nVector index '{settings.vector_index_name}': {vstatus}")

    close_driver()
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
