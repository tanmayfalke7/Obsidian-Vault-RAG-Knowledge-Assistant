"""
Script: reset_project_data.py
Deletes ONLY nodes belonging to this project.
Does NOT touch any other Neo4j data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, close_driver, verify_connectivity
from backend.services.graph_service import delete_project_data, get_graph_stats

configure_logging()


def main():
    print(f"\n{'='*60}")
    print(f"RESET: Project '{settings.project_tag}'")
    print(f"{'='*60}")
    print("⚠️  This will delete all project nodes and relationships.")
    print("⚠️  Other Neo4j data is NOT affected.")
    print()

    confirm = input("Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)

    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    if not verify_connectivity():
        print("❌ Neo4j connection FAILED")
        sys.exit(1)

    print("\nBefore:")
    before = get_graph_stats()
    print(f"  Notes: {before.get('notes',0)}, Chunks: {before.get('chunks',0)}, "
          f"Concepts: {before.get('concepts',0)}, Rels: {before.get('rels',0)}")

    deleted = delete_project_data()
    print(f"\nDeleted: Notes={deleted.get('notes',0)}, Chunks={deleted.get('chunks',0)}, "
          f"Concepts={deleted.get('concepts',0)}")

    print("\nAfter:")
    after = get_graph_stats()
    print(f"  Notes: {after.get('notes',0)}, Chunks: {after.get('chunks',0)}, "
          f"Concepts: {after.get('concepts',0)}, Rels: {after.get('rels',0)}")

    close_driver()
    print(f"\n✓ Reset complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
