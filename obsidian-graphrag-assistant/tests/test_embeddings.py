"""
Integration tests for the embedding service.
Requires GEMINI_API_KEY to be set. Skips if not configured.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def gemini_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.gemini_api_key)
    except Exception:
        return False


@pytest.mark.skipif(not gemini_available(), reason="Gemini API key not configured")
class TestEmbeddingService:
    def setup_method(self):
        from backend.core.config import settings
        from backend.services.embedding_service import init_embedding_service
        init_embedding_service(settings.gemini_api_key, settings.gemini_embedding_model)

    def test_embed_single_text(self):
        from backend.services.embedding_service import embed_text
        from backend.core.config import settings
        embedding = embed_text("What is retrieval augmented generation?")
        assert isinstance(embedding, list)
        assert len(embedding) == settings.embedding_dimensions
        # All values should be floats
        assert all(isinstance(v, float) for v in embedding)

    def test_embed_query_vs_document(self):
        """Query and document embeddings should have same dimensionality."""
        from backend.services.embedding_service import embed_text
        from backend.core.config import settings
        doc_emb = embed_text("RAG combines retrieval with generation.", task_type="RETRIEVAL_DOCUMENT")
        query_emb = embed_text("What is RAG?", task_type="RETRIEVAL_QUERY")
        assert len(doc_emb) == len(query_emb) == settings.embedding_dimensions

    def test_embed_texts_batch(self):
        from backend.services.embedding_service import embed_texts
        from backend.core.config import settings
        texts = ["RAG uses embeddings.", "Neo4j is a graph database.", "Streamlit builds UIs."]
        embeddings = embed_texts(texts, batch_size=3)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == settings.embedding_dimensions

    def test_empty_text_raises(self):
        from backend.services.embedding_service import embed_text
        with pytest.raises((ValueError, Exception)):
            embed_text("")

    def test_similarity_makes_sense(self):
        """Semantically similar texts should have higher cosine similarity."""
        import math
        from backend.services.embedding_service import embed_text
        def cosine(a, b):
            dot = sum(x*y for x,y in zip(a,b))
            mag_a = math.sqrt(sum(x**2 for x in a))
            mag_b = math.sqrt(sum(x**2 for x in b))
            return dot / (mag_a * mag_b + 1e-9)

        emb_rag1 = embed_text("RAG retrieval augmented generation")
        emb_rag2 = embed_text("Retrieval augmented generation combines search and LLMs")
        emb_unrelated = embed_text("The weather in Paris is sunny today")

        sim_related = cosine(emb_rag1, emb_rag2)
        sim_unrelated = cosine(emb_rag1, emb_unrelated)

        assert sim_related > sim_unrelated, (
            f"Expected related texts to be more similar: "
            f"related={sim_related:.3f}, unrelated={sim_unrelated:.3f}"
        )
