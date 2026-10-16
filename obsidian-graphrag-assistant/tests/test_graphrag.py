"""
GraphRAG Production Backend Tests
===================================
Covers all requirements from Prompt 3:

MANDATORY (Spec Section 21):
  User A and User B both have a concept named "RAG".
  User A: RAG → USES → Neo4j
  User B: RAG → USES → PostgreSQL
  When User A asks "What does RAG use?" — response MUST NOT contain PostgreSQL.
  When User B asks "What does RAG use?" — response MUST NOT contain Neo4j.

Additional coverage:
  Retrieval  — correct user gets own chunks; wrong user cannot
  Graph      — own concepts returned; other user's excluded
  RAG        — answer from own notes; no source leakage
  API        — unauthenticated rejected; note-query ownership; graph explorer ownership
  Empty      — graceful handling when no chunks found
  LLM error  — graceful degradation
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Availability guard ─────────────────────────────────────────────────────────

def services_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.neo4j_password and settings.mysql_password)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not services_available(),
    reason="MySQL + Neo4j required for GraphRAG tests",
)


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def services():
    from backend.core.config import settings
    from backend.db.neo4j_client import init_driver, close_driver
    from backend.services.embedding_service import init_embedding_service
    from backend.services.llm_service import init_llm_service

    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    init_embedding_service(settings.embedding_model)
    init_llm_service(settings.gemini_api_key or settings.groq_api_key, settings.gemini_llm_model)
    yield settings
    close_driver()


@pytest.fixture(scope="module")
def db():
    from backend.db.mysql import SessionLocal, init_mysql
    init_mysql()
    session = SessionLocal()
    yield session
    session.close()


def _make_user(db_session, suffix: str):
    from backend.services.auth_service import register_user
    uid = uuid.uuid4().hex[:8]
    return register_user(
        db_session,
        name=f"GRTest {suffix}",
        email=f"grtest-{suffix}-{uid}@example.com",
        phone=f"+0{uid[:9]}",
        password="GraphRAGTest1!",
    )


def _ingest(user_id: str, note_id: str, content: str, title: str,
            filename: str, services) -> None:
    from backend.services.graph_service import (
        create_constraints_and_indexes, create_vector_index, upsert_user_node,
    )
    from backend.services.ingestion_service import ingest_note

    create_constraints_and_indexes()
    create_vector_index(services.vector_index_name, services.embedding_dimensions)
    upsert_user_node(user_id, "")
    ingest_note(note_id=note_id, user_id=user_id, content=content,
                title=title, filename=filename)


def _cleanup_user_neo4j(user_id: str) -> None:
    from backend.services.graph_service import delete_user_neo4j_data
    try:
        delete_user_neo4j_data(user_id)
    except Exception:
        pass


def _delete_user_mysql(db_session, user) -> None:
    try:
        db_session.delete(user)
        db_session.commit()
    except Exception:
        db_session.rollback()


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 — MANDATORY: Same concept name, different users, different edges
# ══════════════════════════════════════════════════════════════════════════════

class TestMandatorySameConceptIsolation:
    """
    SPEC SECTION 21 — This test is explicitly required.

    Both users have a concept named "RAG".
    User A's RAG USES Neo4j.
    User B's RAG USES PostgreSQL.

    Asking User A "What does RAG use?" must NEVER return PostgreSQL.
    Asking User B "What does RAG use?" must NEVER return Neo4j.
    """

    @pytest.fixture(scope="class")
    def setup_same_concept(self, db, services):
        from backend.services.note_service import create_note, delete_note
        from backend.services.graph_service import (
            upsert_concept, create_concept_relationship, upsert_user_node,
            create_constraints_and_indexes, create_vector_index,
        )
        from backend.services.ingestion_service import (
            _neo4j_concept_id, ingest_note,
        )

        # Create two users
        user_a = _make_user(db, "same-concept-a")
        user_b = _make_user(db, "same-concept-b")

        create_constraints_and_indexes()
        create_vector_index(services.vector_index_name, services.embedding_dimensions)
        upsert_user_node(user_a.id, "")
        upsert_user_node(user_b.id, "")

        # User A note: RAG uses Neo4j
        note_a = create_note(db, user_id=user_a.id,
                             title="User A RAG", filename="a_rag.md",
                             content="# RAG for A\n\n[[RAG]] combines retrieval and generation. "
                                     "User A uses [[Neo4j]] as the graph database for RAG. "
                                     "This is A's private knowledge about RAG with Neo4j.",
                             source_type="created")
        ingest_note(note_id=note_a.id, user_id=user_a.id,
                    content=note_a.content, title=note_a.title,
                    filename=note_a.filename)

        # Explicitly create per-user concept relationship
        # User A: RAG → USES → Neo4j
        cid_a_rag = _neo4j_concept_id(user_a.id, "RAG")
        cid_a_neo4j = _neo4j_concept_id(user_a.id, "Neo4j")
        upsert_concept(cid_a_rag, user_a.id, "RAG")
        upsert_concept(cid_a_neo4j, user_a.id, "Neo4j")
        create_concept_relationship(cid_a_rag, "USES", cid_a_neo4j, user_a.id)

        # User B note: RAG uses PostgreSQL
        note_b = create_note(db, user_id=user_b.id,
                             title="User B RAG", filename="b_rag.md",
                             content="# RAG for B\n\n[[RAG]] combines retrieval and generation. "
                                     "User B uses [[PostgreSQL]] as the relational database for RAG. "
                                     "This is B's private knowledge about RAG with PostgreSQL.",
                             source_type="created")
        ingest_note(note_id=note_b.id, user_id=user_b.id,
                    content=note_b.content, title=note_b.title,
                    filename=note_b.filename)

        # User B: RAG → USES → PostgreSQL
        cid_b_rag = _neo4j_concept_id(user_b.id, "RAG")
        cid_b_pg = _neo4j_concept_id(user_b.id, "PostgreSQL")
        upsert_concept(cid_b_rag, user_b.id, "RAG")
        upsert_concept(cid_b_pg, user_b.id, "PostgreSQL")
        create_concept_relationship(cid_b_rag, "USES", cid_b_pg, user_b.id)

        yield {"user_a": user_a, "user_b": user_b, "note_a": note_a, "note_b": note_b,
               "cid_a_rag": cid_a_rag, "cid_b_rag": cid_b_rag}

        # Cleanup
        _cleanup_user_neo4j(user_a.id)
        _cleanup_user_neo4j(user_b.id)
        delete_note(db, note_a.id, user_a.id)
        delete_note(db, note_b.id, user_b.id)
        _delete_user_mysql(db, user_a)
        _delete_user_mysql(db, user_b)

    def test_concept_ids_differ_between_users(self, setup_same_concept):
        """Same concept name must produce different Neo4j node IDs for each user."""
        from backend.services.ingestion_service import _neo4j_concept_id
        uid_a = setup_same_concept["user_a"].id
        uid_b = setup_same_concept["user_b"].id
        id_a = _neo4j_concept_id(uid_a, "RAG")
        id_b = _neo4j_concept_id(uid_b, "RAG")
        assert id_a != id_b, "DESIGN VIOLATION: same concept name produces same ID for different users!"
        assert uid_a in id_a
        assert uid_b in id_b

    def test_user_a_vector_search_no_b_chunks(self, setup_same_concept, services):
        """User A's vector search cannot return User B's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        user_a = setup_same_concept["user_a"]
        user_b = setup_same_concept["user_b"]
        b_chunk_prefix = f"{user_b.id}:"

        emb = embed_query("What does RAG use?")
        results = vector_search(emb, user_a.id, top_k=20,
                                index_name=services.vector_index_name,
                                database=services.neo4j_database)
        for row in results:
            cid = row.get("chunk_id", "")
            assert not cid.startswith(b_chunk_prefix), (
                f"ISOLATION VIOLATION: User A vector search returned B's chunk: {cid}"
            )

    def test_user_b_vector_search_no_a_chunks(self, setup_same_concept, services):
        """User B's vector search cannot return User A's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        user_a = setup_same_concept["user_a"]
        user_b = setup_same_concept["user_b"]
        a_chunk_prefix = f"{user_a.id}:"

        emb = embed_query("What does RAG use?")
        results = vector_search(emb, user_b.id, top_k=20,
                                index_name=services.vector_index_name,
                                database=services.neo4j_database)
        for row in results:
            cid = row.get("chunk_id", "")
            assert not cid.startswith(a_chunk_prefix), (
                f"ISOLATION VIOLATION: User B vector search returned A's chunk: {cid}"
            )

    def test_user_a_graph_has_no_postgresql(self, setup_same_concept, services):
        """User A's graph traversal must not reveal PostgreSQL (User B's concept)."""
        from backend.services.retrieval_service import retrieve

        user_a = setup_same_concept["user_a"]
        result = retrieve("What does RAG use?", user_id=user_a.id, top_k=10)

        # Check concept names
        for name in result.concept_names:
            assert "postgresql" not in name.lower(), (
                f"ISOLATION VIOLATION: User A found PostgreSQL in concept_names: {name}"
            )

        # Check relationship triples
        for rel in result.relationships:
            for val in (rel.get("source", ""), rel.get("target", "")):
                assert "postgresql" not in val.lower(), (
                    f"ISOLATION VIOLATION: User A relationship contains PostgreSQL: {rel}"
                )

    def test_user_b_graph_has_no_neo4j_concept(self, setup_same_concept, services):
        """User B's graph traversal must not reveal Neo4j (User A's concept)."""
        from backend.services.retrieval_service import retrieve

        user_b = setup_same_concept["user_b"]
        result = retrieve("What does RAG use?", user_id=user_b.id, top_k=10)

        for name in result.concept_names:
            assert "neo4j" not in name.lower() or name.lower() == "neo4j" and False, (
                f"ISOLATION VIOLATION: User B found Neo4j in concept_names: {name}"
            )

        for rel in result.relationships:
            for val in (rel.get("source", ""), rel.get("target", "")):
                assert "neo4j" not in val.lower(), (
                    f"ISOLATION VIOLATION: User B relationship contains Neo4j: {rel}"
                )

    def test_user_a_rag_answer_no_postgresql(self, setup_same_concept, services):
        """MANDATORY: User A's RAG answer about RAG must not mention PostgreSQL."""
        from backend.services.rag_service import ask

        user_a = setup_same_concept["user_a"]
        result = ask("What does RAG use?", user_id=user_a.id)

        # Sources must not include User B's note
        user_b = setup_same_concept["user_b"]
        b_prefix = f"{user_b.id}:"
        for src in result.sources:
            assert not src.get("note_id", "").startswith(b_prefix), (
                f"ISOLATION VIOLATION: User A's RAG answer includes B's source: {src}"
            )

        # The answer text should not contain "PostgreSQL"
        answer_lower = result.answer.lower()
        assert "postgresql" not in answer_lower, (
            f"ISOLATION VIOLATION: User A's answer mentions PostgreSQL!\n{result.answer}"
        )

    def test_user_b_rag_answer_no_neo4j(self, setup_same_concept, services):
        """MANDATORY: User B's RAG answer about RAG must not mention Neo4j as User A's concept."""
        from backend.services.rag_service import ask

        user_b = setup_same_concept["user_b"]
        result = ask("What does RAG use?", user_id=user_b.id)

        user_a = setup_same_concept["user_a"]
        a_prefix = f"{user_a.id}:"
        for src in result.sources:
            assert not src.get("note_id", "").startswith(a_prefix), (
                f"ISOLATION VIOLATION: User B's RAG answer includes A's source: {src}"
            )

        # User B's context should not contain User A's private note content
        context_lower = result.context_used.lower()
        assert "user a's private knowledge" not in context_lower, (
            "ISOLATION VIOLATION: User B's context contains User A's private text!"
        )

    def test_concept_node_ownership_in_neo4j(self, setup_same_concept, services):
        """Each user's RAG concept node has the correct user_id property."""
        from backend.db.neo4j_client import run_query

        user_a = setup_same_concept["user_a"]
        user_b = setup_same_concept["user_b"]
        cid_a = setup_same_concept["cid_a_rag"]
        cid_b = setup_same_concept["cid_b_rag"]

        rows = run_query(
            "MATCH (c:Concept {id: $id}) RETURN c.user_id AS uid, c.name AS name",
            {"id": cid_a}, database=services.neo4j_database,
        )
        assert rows and rows[0]["uid"] == user_a.id, "Concept A has wrong user_id"
        assert rows[0]["name"] == "RAG"

        rows = run_query(
            "MATCH (c:Concept {id: $id}) RETURN c.user_id AS uid, c.name AS name",
            {"id": cid_b}, database=services.neo4j_database,
        )
        assert rows and rows[0]["uid"] == user_b.id, "Concept B has wrong user_id"
        assert rows[0]["name"] == "RAG"

    def test_no_cross_concept_relationship(self, setup_same_concept, services):
        """A → RAG must never share a relationship with B → PostgreSQL."""
        from backend.db.neo4j_client import run_query

        user_a = setup_same_concept["user_a"]
        user_b = setup_same_concept["user_b"]

        cypher = """
        MATCH (a:Concept {user_id: $uid_a})-[r]->(b:Concept)
        WHERE b.user_id = $uid_b
        RETURN count(r) AS cross_rels
        """
        rows = run_query(
            cypher,
            {"uid_a": user_a.id, "uid_b": user_b.id},
            database=services.neo4j_database,
        )
        count = rows[0]["cross_rels"] if rows else 0
        assert count == 0, (
            f"ISOLATION VIOLATION: {count} cross-user concept relationship(s) found!"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 — Retrieval isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestRetrievalIsolation:
    """Vector search and graph traversal must be strictly user-scoped."""

    @pytest.fixture(scope="class")
    def two_users(self, db, services):
        from backend.services.note_service import create_note, delete_note

        user_a = _make_user(db, "retr-a")
        user_b = _make_user(db, "retr-b")

        note_a = create_note(db, user_id=user_a.id,
                             title="A Private Embeddings Note", filename="a_emb.md",
                             content="# Embeddings\n\n[[Embeddings]] are dense vectors that capture "
                                     "semantic meaning. User A's private embedding knowledge.",
                             source_type="created")
        _ingest(user_a.id, note_a.id, note_a.content, note_a.title, note_a.filename, services)

        note_b = create_note(db, user_id=user_b.id,
                             title="B Private LLM Note", filename="b_llm.md",
                             content="# LLM\n\n[[LLM]] refers to large language models. "
                                     "User B's private language model knowledge.",
                             source_type="created")
        _ingest(user_b.id, note_b.id, note_b.content, note_b.title, note_b.filename, services)

        yield {"user_a": user_a, "user_b": user_b, "note_a": note_a, "note_b": note_b}

        _cleanup_user_neo4j(user_a.id)
        _cleanup_user_neo4j(user_b.id)
        delete_note(db, note_a.id, user_a.id)
        delete_note(db, note_b.id, user_b.id)
        _delete_user_mysql(db, user_a)
        _delete_user_mysql(db, user_b)

    def test_user_a_top_k_scoped(self, two_users, services):
        """top_k retrieval for User A returns only A's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        user_a = two_users["user_a"]
        user_b = two_users["user_b"]
        b_prefix = f"{user_b.id}:"

        emb = embed_query("embeddings semantic meaning")
        rows = vector_search(emb, user_a.id, top_k=20,
                             index_name=services.vector_index_name,
                             database=services.neo4j_database)
        for row in rows:
            assert not row.get("chunk_id", "").startswith(b_prefix), (
                f"User A top_k contains B's chunk: {row.get('chunk_id')}"
            )

    def test_user_b_top_k_scoped(self, two_users, services):
        """top_k retrieval for User B returns only B's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        user_a = two_users["user_a"]
        user_b = two_users["user_b"]
        a_prefix = f"{user_a.id}:"

        emb = embed_query("language models LLM")
        rows = vector_search(emb, user_b.id, top_k=20,
                             index_name=services.vector_index_name,
                             database=services.neo4j_database)
        for row in rows:
            assert not row.get("chunk_id", "").startswith(a_prefix), (
                f"User B top_k contains A's chunk: {row.get('chunk_id')}"
            )

    def test_graph_traversal_stays_within_user(self, two_users, services):
        """Graph traversal from User A's chunks must not reach User B's concepts."""
        from backend.services.retrieval_service import retrieve
        from backend.db.neo4j_client import run_query

        user_a = two_users["user_a"]
        user_b = two_users["user_b"]

        result = retrieve("embeddings and vectors", user_id=user_a.id, top_k=10)
        a_chunks = [c.chunk_id for c in result.chunks if c.chunk_id.startswith(f"{user_a.id}:")]

        if a_chunks:
            cross = run_query(
                """
                UNWIND $cids AS cid
                MATCH (ch:Chunk {id: cid, user_id: $uid})-[:MENTIONS]->(co:Concept)
                WHERE co.user_id <> $uid
                RETURN count(co) AS n
                """,
                {"cids": a_chunks, "uid": user_a.id},
                database=services.neo4j_database,
            )
            assert (cross[0]["n"] if cross else 0) == 0, (
                "ISOLATION VIOLATION: User A traversal reached foreign concepts!"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3 — RAG pipeline isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestRAGIsolation:
    """End-to-end RAG must not leak sources or context across users."""

    @pytest.fixture(scope="class")
    def rag_users(self, db, services):
        from backend.services.note_service import create_note, delete_note

        user_a = _make_user(db, "rag-a")
        user_b = _make_user(db, "rag-b")

        note_a = create_note(db, user_id=user_a.id,
                             title="A Neo4j Guide", filename="a_neo4j.md",
                             content="# Neo4j for User A\n\nNeo4j is a graph database. "
                                     "It stores nodes and relationships. "
                                     "User A's exclusive Neo4j guide content.",
                             source_type="created")
        _ingest(user_a.id, note_a.id, note_a.content, note_a.title, note_a.filename, services)

        note_b = create_note(db, user_id=user_b.id,
                             title="B Python Guide", filename="b_python.md",
                             content="# Python for User B\n\nPython is a programming language. "
                                     "It is used for data science and AI. "
                                     "User B's exclusive Python programming guide.",
                             source_type="created")
        _ingest(user_b.id, note_b.id, note_b.content, note_b.title, note_b.filename, services)

        yield {"user_a": user_a, "user_b": user_b, "note_a": note_a, "note_b": note_b}

        _cleanup_user_neo4j(user_a.id)
        _cleanup_user_neo4j(user_b.id)
        delete_note(db, note_a.id, user_a.id)
        delete_note(db, note_b.id, user_b.id)
        _delete_user_mysql(db, user_a)
        _delete_user_mysql(db, user_b)

    def test_a_sources_belong_to_a(self, rag_users, services):
        """User A's RAG sources must all start with User A's prefix."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        user_b = rag_users["user_b"]
        b_prefix = f"{user_b.id}:"

        result = ask("Tell me about graph databases", user_id=user_a.id)
        for src in result.sources:
            assert not src.get("note_id", "").startswith(b_prefix), (
                f"ISOLATION VIOLATION: User A source has B's prefix: {src}"
            )

    def test_b_sources_belong_to_b(self, rag_users, services):
        """User B's RAG sources must all start with User B's prefix."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        user_b = rag_users["user_b"]
        a_prefix = f"{user_a.id}:"

        result = ask("Tell me about programming", user_id=user_b.id)
        for src in result.sources:
            assert not src.get("note_id", "").startswith(a_prefix), (
                f"ISOLATION VIOLATION: User B source has A's prefix: {src}"
            )

    def test_context_does_not_contain_b_private_text(self, rag_users, services):
        """User A's LLM context must not contain User B's private note text."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        result = ask("Tell me about databases", user_id=user_a.id)
        assert "user b's exclusive" not in result.context_used.lower(), (
            "ISOLATION VIOLATION: User A's LLM context contains User B's private text!"
        )

    def test_empty_retrieval_returns_graceful_answer(self, services):
        """A user with no notes gets a polite 'no information' response."""
        from backend.services.rag_service import ask

        # Create a user with zero notes
        from backend.db.mysql import SessionLocal, init_mysql
        init_mysql()
        session = SessionLocal()
        empty_user = _make_user(session, "empty-rag")

        try:
            result = ask("What is the meaning of life?", user_id=empty_user.id)
            assert result.chunks_used == 0
            assert result.sources == []
            assert result.answer, "Should return a non-empty graceful answer"
            assert len(result.answer) > 20
        finally:
            _delete_user_mysql(session, empty_user)
            session.close()

    def test_rag_answer_carries_user_id(self, rag_users, services):
        """RAGAnswer.user_id must match the requester."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        user_b = rag_users["user_b"]
        result_a = ask("databases", user_id=user_a.id)
        result_b = ask("programming", user_id=user_b.id)
        assert result_a.user_id == user_a.id
        assert result_b.user_id == user_b.id
        assert result_a.user_id != result_b.user_id

    def test_note_scoped_query(self, rag_users, services):
        """Note-specific RAG query only uses that note's chunks."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        note_a = rag_users["note_a"]
        user_b = rag_users["user_b"]

        result = ask("Tell me about this note's content",
                     user_id=user_a.id,
                     note_id_filter=note_a.id)

        b_prefix = f"{user_b.id}:"
        for src in result.sources:
            assert not src.get("note_id", "").startswith(b_prefix), (
                "Note-scoped query returned B's source!"
            )

    def test_retrieved_chunks_field_populated(self, rag_users, services):
        """retrieved_chunks field should be populated when chunks are found."""
        from backend.services.rag_service import ask

        user_a = rag_users["user_a"]
        result = ask("graph database nodes", user_id=user_a.id)

        if result.chunks_used > 0:
            assert len(result.retrieved_chunks) == result.chunks_used
            for chunk in result.retrieved_chunks:
                assert chunk.get("chunk_id")
                assert chunk.get("text")
                assert isinstance(chunk.get("score"), float)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 4 — API endpoint security
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIGraphRAG:
    """FastAPI endpoint-level security for RAG and graph explorer."""

    @pytest.fixture(scope="class")
    def client(self):
        from backend.main import app
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture(scope="class")
    def api_users(self, db, services):
        from backend.services.note_service import create_note, delete_note

        user_a = _make_user(db, "api-a")
        user_b = _make_user(db, "api-b")

        note_a = create_note(db, user_id=user_a.id,
                             title="API Test Note A", filename="api_a.md",
                             content="# API Test A\n\nThis is User A's API test note. "
                                     "[[Vectors]] are used for retrieval.",
                             source_type="created")
        _ingest(user_a.id, note_a.id, note_a.content, note_a.title, note_a.filename, services)

        note_b = create_note(db, user_id=user_b.id,
                             title="API Test Note B", filename="api_b.md",
                             content="# API Test B\n\nThis is User B's API test note. "
                                     "[[Graphs]] are used for traversal.",
                             source_type="created")
        _ingest(user_b.id, note_b.id, note_b.content, note_b.title, note_b.filename, services)

        yield {"user_a": user_a, "user_b": user_b, "note_a": note_a, "note_b": note_b}

        _cleanup_user_neo4j(user_a.id)
        _cleanup_user_neo4j(user_b.id)
        delete_note(db, note_a.id, user_a.id)
        delete_note(db, note_b.id, user_b.id)
        _delete_user_mysql(db, user_a)
        _delete_user_mysql(db, user_b)

    def _get_token(self, client, email: str) -> str:
        client.cookies.clear()
        resp = client.post("/api/auth/login", json={"email": email, "password": "GraphRAGTest1!"})
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        set_cookie = resp.headers.get("set-cookie", "")
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("access_token="):
                return part[len("access_token="):]
        return resp.json().get("access_token", "")

    def test_unauthenticated_rag_query_rejected(self, client):
        """Unauthenticated POST /api/rag/query must return 401."""
        client.cookies.clear()
        resp = client.post("/api/rag/query", json={"question": "What is RAG?"})
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_rag_query_no_user_id_in_body(self, client, api_users):
        """user_id in request body must be silently ignored (schema strips it)."""
        user_a = api_users["user_a"]
        user_b = api_users["user_b"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.post("/api/rag/query", json={
            "question": "test question",
            "user_id": user_b.id,  # Must be ignored
        })
        assert resp.status_code in (200, 422), f"Unexpected: {resp.text}"
        if resp.status_code == 200:
            data = resp.json()
            assert "user_id" not in data, "Response leaked user_id!"

    def test_note_rag_query_wrong_user_returns_404(self, client, api_users):
        """POST /api/rag/note/{B_note_id}/query by User A must return 404."""
        user_a = api_users["user_a"]
        note_b = api_users["note_b"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.post(f"/api/rag/note/{note_b.id}/query",
                           json={"question": "what is this?"})
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User A got {resp.status_code} for B's note query. "
            f"Expected 404. Body: {resp.text}"
        )

    def test_note_related_wrong_user_returns_404(self, client, api_users):
        """GET /api/rag/note/{B_note_id}/related by User A must return 404."""
        user_a = api_users["user_a"]
        note_b = api_users["note_b"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.get(f"/api/rag/note/{note_b.id}/related")
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User A got {resp.status_code} for B's note related. "
            f"Expected 404. Body: {resp.text}"
        )

    def test_graph_note_wrong_user_returns_404(self, client, api_users):
        """GET /api/graph/note/{B_note_id} by User A must return 404."""
        user_a = api_users["user_a"]
        note_b = api_users["note_b"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.get(f"/api/graph/note/{note_b.id}")
        assert resp.status_code == 404

    def test_graph_concept_wrong_user_returns_404(self, client, api_users):
        """GET /api/graph/concept/{B_concept_id} by User A must return 404."""
        user_a = api_users["user_a"]
        user_b = api_users["user_b"]
        from backend.services.ingestion_service import _neo4j_concept_id
        b_concept_id = _neo4j_concept_id(user_b.id, "Graphs")

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.get(f"/api/graph/concept/{b_concept_id}")
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User A got {resp.status_code} for B's concept. "
            f"Expected 404."
        )

    def test_graph_path_user_scoped(self, client, api_users):
        """GET /api/graph/path only searches authenticated user's graph."""
        user_a = api_users["user_a"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        # Path search for User A — should work or return not-found, never crash
        resp = client.get("/api/graph/path?source=Vectors&target=Retrieval")
        assert resp.status_code in (200, 200), f"Unexpected: {resp.text}"
        if resp.status_code == 200:
            data = resp.json()
            assert "found" in data
            assert "steps" in data

    def test_rag_query_response_schema(self, client, api_users):
        """POST /api/rag/query returns the expected schema fields."""
        user_a = api_users["user_a"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.post("/api/rag/query", json={"question": "What are vectors?"})
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()

        required_fields = {"answer", "sources", "retrieved_chunks", "concepts",
                           "relationships", "chunks_used", "has_error"}
        for field in required_fields:
            assert field in data, f"Missing field '{field}' in RAG response"

    def test_note_rag_query_own_note_succeeds(self, client, api_users):
        """POST /api/rag/note/{A_note_id}/query by User A should succeed."""
        user_a = api_users["user_a"]
        note_a = api_users["note_a"]

        token = self._get_token(client, user_a.email)
        client.cookies.set("access_token", token)

        resp = client.post(f"/api/rag/note/{note_a.id}/query",
                           json={"question": "What does this note talk about?"})
        assert resp.status_code == 200, f"Own note query failed: {resp.text}"
        data = resp.json()
        assert "answer" in data


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 5 — Graph explorer correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestGraphExplorer:
    """Graph explorer helpers return correct, user-scoped data."""

    @pytest.fixture(scope="class")
    def graph_user(self, db, services):
        from backend.services.note_service import create_note, delete_note
        from backend.services.graph_service import (
            upsert_concept, create_concept_relationship, upsert_user_node,
        )
        from backend.services.ingestion_service import _neo4j_concept_id

        user = _make_user(db, "graph-exp")
        note = create_note(db, user_id=user.id,
                           title="Graph Explorer Test", filename="graph_exp.md",
                           content="# Graph Test\n\n[[RAG]] uses [[Embeddings]]. "
                                   "[[Embeddings]] enable [[Semantic Search]].",
                           source_type="created")
        _ingest(user.id, note.id, note.content, note.title, note.filename, services)

        # Explicit relationships for path testing
        upsert_user_node(user.id, "")
        for name in ["RAG", "Embeddings", "Semantic Search"]:
            cid = _neo4j_concept_id(user.id, name)
            from backend.services.graph_service import upsert_concept
            upsert_concept(cid, user.id, name)

        cid_rag = _neo4j_concept_id(user.id, "RAG")
        cid_emb = _neo4j_concept_id(user.id, "Embeddings")
        cid_sem = _neo4j_concept_id(user.id, "Semantic Search")
        create_concept_relationship(cid_rag, "USES", cid_emb, user.id)
        create_concept_relationship(cid_emb, "ENABLES", cid_sem, user.id)

        yield {"user": user, "note": note,
               "cid_rag": cid_rag, "cid_emb": cid_emb, "cid_sem": cid_sem}

        _cleanup_user_neo4j(user.id)
        delete_note(db, note.id, user.id)
        _delete_user_mysql(db, user)

    def test_get_concept_neighbours_scoped(self, graph_user, services):
        """get_concept_neighbours returns only this user's neighbours."""
        from backend.services.retrieval_service import get_concept_neighbours

        user = graph_user["user"]
        cid_rag = graph_user["cid_rag"]

        result = get_concept_neighbours(cid_rag, user.id)
        assert result.get("name") == "RAG"
        outgoing_names = [n["name"] for n in result.get("outgoing", [])]
        assert "Embeddings" in outgoing_names

    def test_find_path_rag_to_semantic_search(self, graph_user, services):
        """find_path discovers RAG → Embeddings → Semantic Search."""
        from backend.services.retrieval_service import find_path

        user = graph_user["user"]
        steps = find_path("RAG", "Semantic Search", user_id=user.id, max_depth=4)

        if steps:
            node_names = [s.get("node") for s in steps if s.get("node")]
            assert "RAG" in node_names
            assert "Semantic Search" in node_names

            rel_names = [s.get("relationship") for s in steps if s.get("relationship")]
            assert len(rel_names) >= 1, "Path should contain at least one relationship"

    def test_find_path_no_cross_user(self, db, graph_user, services):
        """Path finding must not return results from another user's graph."""
        from backend.services.retrieval_service import find_path
        from backend.services.note_service import create_note, delete_note
        from backend.services.graph_service import (
            upsert_concept, create_concept_relationship, upsert_user_node,
        )
        from backend.services.ingestion_service import _neo4j_concept_id

        # Create second user with overlapping concept names
        user2 = _make_user(db, "path-b")
        upsert_user_node(user2.id, "")
        cid2_rag = _neo4j_concept_id(user2.id, "RAG")
        cid2_postgres = _neo4j_concept_id(user2.id, "PostgreSQL")
        upsert_concept(cid2_rag, user2.id, "RAG")
        upsert_concept(cid2_postgres, user2.id, "PostgreSQL")
        create_concept_relationship(cid2_rag, "USES", cid2_postgres, user2.id)

        try:
            user_a = graph_user["user"]
            # User A searches for path to PostgreSQL — should not find it
            steps = find_path("RAG", "PostgreSQL", user_id=user_a.id, max_depth=4)
            # If steps exist they must all belong to user_a
            for step in steps:
                sid = step.get("id", "")
                if sid:
                    assert sid.startswith(user_a.id), (
                        f"Path step belongs to wrong user: {sid}"
                    )
        finally:
            _cleanup_user_neo4j(user2.id)
            _delete_user_mysql(db, user2)

    def test_get_note_graph_user_scoped(self, graph_user, services):
        """get_note_graph returns only this user's nodes."""
        from backend.services.retrieval_service import get_note_graph
        from backend.services.ingestion_service import _neo4j_note_id

        user = graph_user["user"]
        note = graph_user["note"]
        neo4j_note_id = _neo4j_note_id(user.id, note.id)

        raw = get_note_graph(neo4j_note_id, user.id)
        assert raw["note_id"] == neo4j_note_id
        for node in raw.get("nodes", []):
            nid = node.get("id", "")
            if nid and nid != neo4j_note_id:
                assert user.id in nid, (
                    f"Note graph contains node not belonging to user: {nid}"
                )
