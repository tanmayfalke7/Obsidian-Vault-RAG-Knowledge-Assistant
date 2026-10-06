"""
Integration tests for the fastembed embedding service.
No API key required — fastembed runs locally.
"""
import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def embedding_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.embedding_model)
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def init_embedding(request):
    if not embedding_available():
        pytest.skip("Embedding model not configured")
    from backend.core.config import settings
    from backend.services.embedding_service import init_embedding_service
    init_embedding_service(settings.embedding_model)


@pytest.mark.skipif(not embedding_available(), reason="Embedding model not configured")
class TestEmbeddingService:

    def test_embed_single_text(self):
        from backend.services.embedding_service import embed_text
        from backend.core.config import settings
        embedding = embed_text("What is retrieval augmented generation?")
        assert isinstance(embedding, list)
        assert len(embedding) == settings.embedding_dimensions
        assert all(isinstance(v, float) for v in embedding)

    def test_embed_texts_batch(self):
        from backend.services.embedding_service import embed_texts
        from backend.core.config import settings
        texts = ["RAG uses embeddings.", "Neo4j is a graph database.", "FastAPI builds APIs."]
        embeddings = embed_texts(texts)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == settings.embedding_dimensions

    def test_empty_text_raises(self):
        from backend.services.embedding_service import embed_text
        with pytest.raises((ValueError, Exception)):
            embed_text("")

    def test_embed_query(self):
        from backend.services.embedding_service import embed_query
        from backend.core.config import settings
        emb = embed_query("What is RAG?")
        assert isinstance(emb, list)
        assert len(emb) == settings.embedding_dimensions

    def test_similarity_makes_sense(self):
        """Semantically similar texts should have higher cosine similarity."""
        from backend.services.embedding_service import embed_text

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            mag_a = math.sqrt(sum(x ** 2 for x in a))
            mag_b = math.sqrt(sum(x ** 2 for x in b))
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
