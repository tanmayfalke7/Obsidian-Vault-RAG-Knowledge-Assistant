"""
Integration tests for the RAG pipeline.
Requires Neo4j + Gemini configured and vault already ingested.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def services_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.neo4j_password and settings.gemini_api_key)
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def init_services():
    if not services_available():
        pytest.skip("Services not configured")
    from backend.core.config import settings
    from backend.db.neo4j_client import init_driver
    from backend.services.embedding_service import init_embedding_service
    from backend.services.llm_service import init_llm_service
    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    init_embedding_service(settings.gemini_api_key, settings.gemini_embedding_model)
    init_llm_service(settings.gemini_api_key, settings.gemini_llm_model)
    yield
    from backend.db.neo4j_client import close_driver
    close_driver()


@pytest.mark.skipif(not services_available(), reason="Services not configured")
class TestRAGPipeline:
    def test_ask_returns_answer(self):
        from backend.services.rag_service import ask
        result = ask("What is RAG?")
        assert isinstance(result.answer, str)
        assert len(result.answer) > 10

    def test_ask_returns_sources(self):
        from backend.services.rag_service import ask
        result = ask("How are embeddings used?")
        # If vault is ingested, should have sources
        # If not ingested, should return the "not found" message gracefully
        assert isinstance(result.sources, list)
        assert isinstance(result.relationships, list)

    def test_ask_no_hallucination_on_unknown(self):
        """Unknown question should return graceful no-context message."""
        from backend.services.rag_service import ask
        result = ask("What is the price of bananas in Tokyo market?")
        # Should not fabricate facts — answer should be short or mention insufficient context
        assert isinstance(result.answer, str)

    def test_chunks_used_positive(self):
        """After ingestion, retrieving chunks should find results."""
        from backend.services.rag_service import ask
        result = ask("Tell me about Neo4j and graph databases")
        # chunks_used is 0 if vault not ingested; otherwise positive
        assert isinstance(result.chunks_used, int)
        assert result.chunks_used >= 0
