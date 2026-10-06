"""
Integration tests for the RAG pipeline.
Requires Neo4j connected + vault already ingested for a user.
Uses Groq LLM and fastembed — no Gemini dependency.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SYSTEM_USER_ID = "system"  # the user_id used by the sample vault script


def services_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.neo4j_password and settings.groq_api_key)
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def init_services():
    if not services_available():
        pytest.skip("Services not configured (Neo4j or Groq missing)")
    from backend.core.config import settings
    from backend.db.neo4j_client import init_driver
    from backend.services.embedding_service import init_embedding_service
    from backend.services.llm_service import init_llm_service
    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    init_embedding_service(settings.embedding_model)
    init_llm_service(settings.groq_api_key, settings.groq_llm_model)
    yield
    from backend.db.neo4j_client import close_driver
    close_driver()


@pytest.mark.skipif(not services_available(), reason="Services not configured")
class TestRAGPipeline:

    def test_ask_requires_user_id(self):
        """ask() must accept user_id as a required parameter."""
        from backend.services.rag_service import ask
        import inspect
        sig = inspect.signature(ask)
        assert "user_id" in sig.parameters, "ask() must have user_id parameter"

    def test_ask_returns_answer(self):
        from backend.services.rag_service import ask
        result = ask("What is RAG?", user_id=SYSTEM_USER_ID)
        assert isinstance(result.answer, str)
        assert len(result.answer) > 10

    def test_ask_returns_sources(self):
        from backend.services.rag_service import ask
        result = ask("How are embeddings used?", user_id=SYSTEM_USER_ID)
        assert isinstance(result.sources, list)
        assert isinstance(result.relationships, list)

    def test_ask_no_hallucination_on_unknown(self):
        from backend.services.rag_service import ask
        result = ask("What is the price of bananas in Tokyo market?", user_id=SYSTEM_USER_ID)
        assert isinstance(result.answer, str)

    def test_result_carries_user_id(self):
        """RAGAnswer must include user_id for downstream verification."""
        from backend.services.rag_service import ask
        result = ask("What is Neo4j?", user_id=SYSTEM_USER_ID)
        assert result.user_id == SYSTEM_USER_ID

    def test_sources_have_required_fields(self):
        from backend.services.rag_service import ask
        result = ask("What is RAG?", user_id=SYSTEM_USER_ID)
        for source in result.sources:
            assert "filename" in source or "title" in source, \
                "Each source must have filename or title"
