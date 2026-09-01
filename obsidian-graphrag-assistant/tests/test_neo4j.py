"""
Integration tests for Neo4j connectivity and basic operations.
Requires a running Neo4j instance and valid .env.

Skips automatically if NEO4J_PASSWORD is not set.
"""
import pytest
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def neo4j_available() -> bool:
    """Check if Neo4j credentials are configured."""
    try:
        from backend.core.config import settings
        return bool(settings.neo4j_password)
    except Exception:
        return False


@pytest.mark.skipif(not neo4j_available(), reason="Neo4j credentials not configured")
class TestNeo4jConnection:
    def setup_method(self):
        from backend.core.config import settings
        from backend.db.neo4j_client import init_driver
        init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)

    def teardown_method(self):
        from backend.db.neo4j_client import close_driver
        close_driver()

    def test_verify_connectivity(self):
        from backend.db.neo4j_client import verify_connectivity
        assert verify_connectivity() is True

    def test_simple_query(self):
        from backend.db.neo4j_client import run_query
        from backend.core.config import settings
        results = run_query("RETURN 1 AS n", database=settings.neo4j_database)
        assert results[0]["n"] == 1

    def test_create_and_delete_test_node(self):
        from backend.db.neo4j_client import run_query
        from backend.core.config import settings
        db = settings.neo4j_database
        # Create
        run_query(
            "MERGE (n:_TestNode {id: 'pytest-test'}) SET n.value = 42",
            database=db,
        )
        # Read
        result = run_query(
            "MATCH (n:_TestNode {id: 'pytest-test'}) RETURN n.value AS v",
            database=db,
        )
        assert result[0]["v"] == 42
        # Cleanup
        run_query(
            "MATCH (n:_TestNode {id: 'pytest-test'}) DELETE n",
            database=db,
        )
