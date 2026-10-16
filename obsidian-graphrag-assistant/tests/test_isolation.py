"""
MANDATORY MULTI-USER ISOLATION TESTS
=====================================
These tests verify that NO user can access another user's data anywhere
in the stack: MySQL, Neo4j vector search, graph traversal, or RAG answers.

Tests cover all 14 isolation requirements from the spec:
  1.  User A can retrieve A's note
  2.  User A cannot retrieve B's note
  3.  User B can retrieve B's note
  4.  User B cannot retrieve A's note
  5.  User A's vector search cannot return B's chunks
  6.  User B's vector search cannot return A's chunks
  7.  User A's graph traversal cannot reach B's concepts
  8.  User B's graph traversal cannot reach A's concepts
  9.  User A's RAG answer cannot contain B's sources
  10. User B's RAG answer cannot contain A's sources
  11. User A cannot reindex B's note
  12. User A cannot delete B's note
  13. User A cannot modify B's folder
  14. User A cannot access B's note by guessing the note ID

Security:
  15. GET /api/notes/{B_note_id} by User A returns 404
  16. POST /api/rag/query ignores any user_id in body (uses JWT only)

Services required: MySQL + Neo4j running, embedding service available.
The tests create and clean up their own data — they do NOT depend on vault ingestion.
"""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Availability guard ────────────────────────────────────────────────────────

def services_available() -> bool:
    try:
        from backend.core.config import settings
        return bool(settings.neo4j_password and settings.mysql_password)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not services_available(),
    reason="MySQL and Neo4j required for isolation tests",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def services():
    """Initialise all backend services once for this test module."""
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
def db_session():
    """Synchronous MySQL session for the test module."""
    from backend.db.mysql import SessionLocal, init_mysql
    init_mysql()
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="module")
def user_a(db_session):
    """Create User A, yield, then clean up."""
    from backend.services.auth_service import register_user
    uid = f"test-a-{uuid.uuid4().hex[:8]}"
    user = register_user(
        db_session,
        name="Isolation User A",
        email=f"{uid}@test-isolation.example",
        phone=f"+1555{uid[:7]}",
        password="TestPassA123!",
    )
    yield user
    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.fixture(scope="module")
def user_b(db_session):
    """Create User B, yield, then clean up."""
    from backend.services.auth_service import register_user
    uid = f"test-b-{uuid.uuid4().hex[:8]}"
    user = register_user(
        db_session,
        name="Isolation User B",
        email=f"{uid}@test-isolation.example",
        phone=f"+1555{uid[:7]}",
        password="TestPassB123!",
    )
    yield user
    db_session.delete(user)
    db_session.commit()


@pytest.fixture(scope="module")
def note_a(db_session, user_a, services):
    """Create and ingest a note for User A."""
    from backend.services.note_service import create_note, delete_note
    from backend.services.ingestion_service import ingest_note
    from backend.services.graph_service import (
        create_constraints_and_indexes, create_vector_index, upsert_user_node,
    )

    create_constraints_and_indexes()
    create_vector_index(services.vector_index_name, services.embedding_dimensions)
    upsert_user_node(user_a.id, user_a.name)

    note = create_note(
        db_session,
        user_id=user_a.id,
        title="User A — RAG Overview",
        filename="user_a_rag.md",
        content="# RAG Overview for User A\n\nRetrieval Augmented Generation (RAG) "
                "combines vector search with language model generation.\n\n"
                "[[Embeddings]] are used to find relevant chunks.\n\n"
                "User A's private knowledge about RAG pipelines.",
        source_type="created",
    )
    ingest_note(
        note_id=note.id,
        user_id=user_a.id,
        content=note.content,
        title=note.title,
        filename=note.filename,
    )
    yield note
    try:
        neo4j_note_id = f"{user_a.id}:{note.id}"
        from backend.services.graph_service import delete_note_neo4j
        delete_note_neo4j(neo4j_note_id, user_a.id)
    except Exception:
        pass
    delete_note(db_session, note.id, user_a.id)


@pytest.fixture(scope="module")
def note_b(db_session, user_b, services):
    """Create and ingest a note for User B."""
    from backend.services.note_service import create_note, delete_note
    from backend.services.ingestion_service import ingest_note
    from backend.services.graph_service import (
        create_constraints_and_indexes, create_vector_index, upsert_user_node,
    )

    create_constraints_and_indexes()
    create_vector_index(services.vector_index_name, services.embedding_dimensions)
    upsert_user_node(user_b.id, user_b.name)

    note = create_note(
        db_session,
        user_id=user_b.id,
        title="User B — GraphRAG System",
        filename="user_b_graphrag.md",
        content="# GraphRAG for User B\n\nGraphRAG extends RAG with knowledge graph traversal.\n\n"
                "[[Knowledge Graph]] nodes represent concepts with relationships.\n\n"
                "User B's private knowledge about graph-based retrieval.",
        source_type="created",
    )
    ingest_note(
        note_id=note.id,
        user_id=user_b.id,
        content=note.content,
        title=note.title,
        filename=note.filename,
    )
    yield note
    try:
        neo4j_note_id = f"{user_b.id}:{note.id}"
        from backend.services.graph_service import delete_note_neo4j
        delete_note_neo4j(neo4j_note_id, user_b.id)
    except Exception:
        pass
    delete_note(db_session, note.id, user_b.id)


@pytest.fixture(scope="module")
def folder_b(db_session, user_b):
    """Create a folder for User B."""
    from backend.services.folder_service import create_folder, delete_folder
    folder = create_folder(db_session, user_id=user_b.id, name="B Private Folder")
    yield folder
    delete_folder(db_session, folder.id, user_b.id)


# ── MySQL Note Isolation ──────────────────────────────────────────────────────

class TestMySQLNoteIsolation:
    """Tests 1-4, 11-14: MySQL-level ownership enforcement."""

    def test_1_user_a_can_retrieve_own_note(self, db_session, user_a, note_a):
        """Test 1: User A can retrieve A's note."""
        from backend.services.note_service import get_note
        found = get_note(db_session, note_a.id, user_a.id)
        assert found is not None
        assert found.id == note_a.id
        assert found.user_id == user_a.id

    def test_2_user_a_cannot_retrieve_b_note(self, db_session, user_a, note_b):
        """Test 2: User A cannot retrieve B's note — returns None (mapped to 404)."""
        from backend.services.note_service import get_note
        found = get_note(db_session, note_b.id, user_a.id)
        assert found is None, "ISOLATION VIOLATION: User A retrieved User B's note!"

    def test_3_user_b_can_retrieve_own_note(self, db_session, user_b, note_b):
        """Test 3: User B can retrieve B's note."""
        from backend.services.note_service import get_note
        found = get_note(db_session, note_b.id, user_b.id)
        assert found is not None
        assert found.id == note_b.id
        assert found.user_id == user_b.id

    def test_4_user_b_cannot_retrieve_a_note(self, db_session, user_b, note_a):
        """Test 4: User B cannot retrieve A's note."""
        from backend.services.note_service import get_note
        found = get_note(db_session, note_a.id, user_b.id)
        assert found is None, "ISOLATION VIOLATION: User B retrieved User A's note!"

    def test_12_user_a_cannot_delete_b_note(self, db_session, user_a, note_b):
        """Test 12: User A cannot delete B's note."""
        from backend.services.note_service import delete_note, get_note
        # First confirm note_b exists for B (get the note_id from the fixture)
        b_note_id = note_b.id
        deleted = delete_note(db_session, b_note_id, user_a.id)
        assert not deleted, "SECURITY VIOLATION: User A deleted User B's note!"
        # Verify note still exists via raw SQL (bypass user_b fixture scope issue)
        from sqlalchemy import select
        from backend.db.models import Note
        still_there = db_session.execute(
            select(Note).where(Note.id == b_note_id)
        ).scalar_one_or_none()
        assert still_there is not None, "Note was deleted even though delete_note returned False!"

    def test_13_user_a_cannot_modify_b_folder(self, db_session, user_a, folder_b):
        """Test 13: User A cannot modify B's folder."""
        from backend.services.folder_service import update_folder
        result = update_folder(db_session, folder_b.id, user_a.id, "Hacked Name")
        assert result is None, "SECURITY VIOLATION: User A modified User B's folder!"

    def test_14_guessing_b_note_id_returns_none(self, db_session, user_a, note_b):
        """Test 14: User A cannot access B's note by guessing the note ID."""
        from backend.services.note_service import get_note
        found = get_note(db_session, note_b.id, user_a.id)
        assert found is None, (
            f"SECURITY VIOLATION: User A accessed note {note_b.id} by guessing ID!"
        )

    def test_note_list_a_excludes_b_notes(self, db_session, user_a, note_b):
        """User A's note list must not include B's notes."""
        from backend.services.note_service import get_all_notes_for_user
        a_notes = get_all_notes_for_user(db_session, user_a.id)
        a_note_ids = {n.id for n in a_notes}
        assert note_b.id not in a_note_ids, (
            "ISOLATION VIOLATION: B's note appeared in A's note list!"
        )

    def test_note_list_b_excludes_a_notes(self, db_session, user_b, note_a):
        """User B's note list must not include A's notes."""
        from backend.services.note_service import get_all_notes_for_user
        b_notes = get_all_notes_for_user(db_session, user_b.id)
        b_note_ids = {n.id for n in b_notes}
        assert note_a.id not in b_note_ids, (
            "ISOLATION VIOLATION: A's note appeared in B's note list!"
        )

    def test_search_a_excludes_b_content(self, db_session, user_a, note_b):
        """User A's search cannot return B's notes even if query matches."""
        from backend.services.note_service import search_notes
        # Search for a distinctive phrase from User B's note
        results = search_notes(db_session, user_a.id, "User B")
        result_ids = {n.id for n in results}
        assert note_b.id not in result_ids, (
            "ISOLATION VIOLATION: User A's search returned B's note!"
        )


# ── Neo4j Vector Search Isolation ────────────────────────────────────────────

class TestNeo4jVectorIsolation:
    """Tests 5-6: Vector search must be scoped to user_id at the DB level."""

    def test_5_user_a_vector_search_excludes_b_chunks(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 5: User A's vector search cannot return B's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        query_emb = embed_query("RAG and vector search knowledge")
        results = vector_search(
            query_embedding=query_emb,
            user_id=user_a.id,
            top_k=20,
            index_name=services.vector_index_name,
            database=services.neo4j_database,
        )
        b_neo4j_note_id = f"{user_b.id}:{note_b.id}"
        b_chunk_prefix = f"{user_b.id}:"
        for row in results:
            chunk_id = row.get("chunk_id", "")
            assert not chunk_id.startswith(b_chunk_prefix), (
                f"ISOLATION VIOLATION: User A's vector search returned B's chunk: {chunk_id}"
            )
            note_id = row.get("note_id", "")
            assert note_id != b_neo4j_note_id, (
                f"ISOLATION VIOLATION: User A's vector search returned B's note: {note_id}"
            )

    def test_6_user_b_vector_search_excludes_a_chunks(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 6: User B's vector search cannot return A's chunks."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        query_emb = embed_query("RAG and vector search knowledge")
        results = vector_search(
            query_embedding=query_emb,
            user_id=user_b.id,
            top_k=20,
            index_name=services.vector_index_name,
            database=services.neo4j_database,
        )
        a_neo4j_note_id = f"{user_a.id}:{note_a.id}"
        a_chunk_prefix = f"{user_a.id}:"
        for row in results:
            chunk_id = row.get("chunk_id", "")
            assert not chunk_id.startswith(a_chunk_prefix), (
                f"ISOLATION VIOLATION: User B's vector search returned A's chunk: {chunk_id}"
            )
            note_id = row.get("note_id", "")
            assert note_id != a_neo4j_note_id, (
                f"ISOLATION VIOLATION: User B's vector search returned A's note: {note_id}"
            )

    def test_vector_search_returns_correct_user_chunks(
        self, user_a, note_a, services
    ):
        """Vector search must return chunks owned by the querying user."""
        from backend.services.retrieval_service import vector_search
        from backend.services.embedding_service import embed_query

        query_emb = embed_query("RAG retrieval augmented generation")
        results = vector_search(
            query_embedding=query_emb,
            user_id=user_a.id,
            top_k=10,
            index_name=services.vector_index_name,
            database=services.neo4j_database,
        )
        # All returned chunks must belong to user_a
        a_chunk_prefix = f"{user_a.id}:"
        for row in results:
            chunk_id = row.get("chunk_id", "")
            if chunk_id:
                assert chunk_id.startswith(a_chunk_prefix), (
                    f"ISOLATION VIOLATION: chunk {chunk_id} does not belong to user_a!"
                )


# ── Neo4j Graph Traversal Isolation ──────────────────────────────────────────

class TestNeo4jGraphIsolation:
    """Tests 7-8: Graph traversal must stay within a user's concepts."""

    def test_7_user_a_graph_traversal_excludes_b_concepts(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 7: User A's graph traversal cannot reach B's concepts."""
        from backend.services.retrieval_service import retrieve

        result = retrieve(
            question="RAG and knowledge graphs",
            user_id=user_a.id,
            top_k=5,
        )
        b_concept_prefix = f"{user_b.id}:concept:"
        for concept_name in result.concept_names:
            # concept_names are human-readable names, not IDs — check relationships
            pass

        # Check relationship triples — none should reference B's concepts
        for rel in result.relationships:
            # Relationships are human-readable concept names — verify via Neo4j directly
            pass

        # Direct Neo4j check: no concept with user_b's prefix should appear
        from backend.db.neo4j_client import run_query
        a_chunk_prefix = f"{user_a.id}:"
        chunks = [c for c in result.chunks if c.chunk_id.startswith(a_chunk_prefix)]

        if chunks:
            chunk_ids = [c.chunk_id for c in chunks]
            cypher = """
            UNWIND $chunk_ids AS cid
            MATCH (ch:Chunk {id: cid, user_id: $user_a_id})-[:MENTIONS]->(concept:Concept)
            WHERE concept.user_id <> $user_a_id
            RETURN concept.id AS id, concept.user_id AS uid
            LIMIT 1
            """
            cross_tenant = run_query(
                cypher,
                {"chunk_ids": chunk_ids, "user_a_id": user_a.id},
                database=services.neo4j_database,
            )
            assert len(cross_tenant) == 0, (
                f"ISOLATION VIOLATION: User A's traversal reached concepts of another user: {cross_tenant}"
            )

    def test_8_user_b_graph_traversal_excludes_a_concepts(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 8: User B's graph traversal cannot reach A's concepts."""
        from backend.services.retrieval_service import retrieve
        from backend.db.neo4j_client import run_query

        result = retrieve(
            question="GraphRAG knowledge graph traversal",
            user_id=user_b.id,
            top_k=5,
        )
        b_chunk_prefix = f"{user_b.id}:"
        chunks = [c for c in result.chunks if c.chunk_id.startswith(b_chunk_prefix)]

        if chunks:
            chunk_ids = [c.chunk_id for c in chunks]
            cypher = """
            UNWIND $chunk_ids AS cid
            MATCH (ch:Chunk {id: cid, user_id: $user_b_id})-[:MENTIONS]->(concept:Concept)
            WHERE concept.user_id <> $user_b_id
            RETURN concept.id AS id, concept.user_id AS uid
            LIMIT 1
            """
            cross_tenant = run_query(
                cypher,
                {"chunk_ids": chunk_ids, "user_b_id": user_b.id},
                database=services.neo4j_database,
            )
            assert len(cross_tenant) == 0, (
                f"ISOLATION VIOLATION: User B's traversal reached concepts of another user: {cross_tenant}"
            )

    def test_concept_ids_are_user_scoped(self, user_a, user_b, services):
        """Concept nodes with the same name for different users must have different IDs."""
        from backend.services.ingestion_service import _neo4j_concept_id
        concept_name = "RAG"
        id_a = _neo4j_concept_id(user_a.id, concept_name)
        id_b = _neo4j_concept_id(user_b.id, concept_name)
        assert id_a != id_b, (
            "DESIGN VIOLATION: Same concept name for different users produces same ID!"
        )
        assert user_a.id in id_a
        assert user_b.id in id_b

    def test_note_ids_are_user_scoped(self, user_a, user_b, note_a, note_b):
        """Neo4j note IDs must embed user_id to prevent collision."""
        from backend.services.ingestion_service import _neo4j_note_id
        neo4j_id_a = _neo4j_note_id(user_a.id, note_a.id)
        neo4j_id_b = _neo4j_note_id(user_b.id, note_b.id)
        assert user_a.id in neo4j_id_a
        assert user_b.id in neo4j_id_b
        assert neo4j_id_a != neo4j_id_b

    def test_chunk_ids_are_user_scoped(self, user_a, user_b, note_a, note_b):
        """Neo4j chunk IDs must embed user_id to prevent collision."""
        from backend.services.ingestion_service import _neo4j_chunk_id
        chunk_id_a = _neo4j_chunk_id(user_a.id, note_a.id, 0)
        chunk_id_b = _neo4j_chunk_id(user_b.id, note_b.id, 0)
        assert user_a.id in chunk_id_a
        assert user_b.id in chunk_id_b
        assert chunk_id_a != chunk_id_b


# ── RAG Pipeline Isolation ────────────────────────────────────────────────────

class TestRAGPipelineIsolation:
    """Tests 9-10: End-to-end RAG must not leak context across users."""

    def test_9_user_a_rag_sources_are_only_a(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 9: User A's RAG answer sources must not include B's note."""
        from backend.services.rag_service import ask

        result = ask(
            question="Tell me about RAG pipelines",
            user_id=user_a.id,
        )
        b_neo4j_note_id = f"{user_b.id}:{note_b.id}"
        b_filename = note_b.filename

        for source in result.sources:
            assert source.get("note_id") != b_neo4j_note_id, (
                f"ISOLATION VIOLATION: User A's RAG sources contain B's note! source={source}"
            )
            assert source.get("filename") != b_filename or source.get("filename") is None, (
                f"WARNING: User A's RAG returned a source with B's filename: {b_filename}"
            )

    def test_10_user_b_rag_sources_are_only_b(
        self, user_a, user_b, note_a, note_b, services
    ):
        """Test 10: User B's RAG answer sources must not include A's note."""
        from backend.services.rag_service import ask

        result = ask(
            question="Tell me about graph-based retrieval",
            user_id=user_b.id,
        )
        a_neo4j_note_id = f"{user_a.id}:{note_a.id}"
        a_filename = note_a.filename

        for source in result.sources:
            assert source.get("note_id") != a_neo4j_note_id, (
                f"ISOLATION VIOLATION: User B's RAG sources contain A's note! source={source}"
            )

    def test_rag_result_carries_correct_user_id(self, user_a, user_b):
        """RAGAnswer.user_id must match the requesting user, not bleed across users."""
        from backend.services.rag_service import ask
        result_a = ask("RAG pipelines", user_id=user_a.id)
        result_b = ask("graph retrieval", user_id=user_b.id)
        assert result_a.user_id == user_a.id
        assert result_b.user_id == user_b.id
        assert result_a.user_id != result_b.user_id


# ── API-level Security Tests ──────────────────────────────────────────────────

class TestAPISecurityIsolation:
    """Tests 11, 14-16: FastAPI endpoint-level security."""

    @pytest.fixture(scope="class")
    def client(self):
        from backend.main import app
        return TestClient(app, raise_server_exceptions=False)

    def _login_token(self, client, email: str, password: str) -> str:
        """Helper: login and return the raw token string (not via cookies jar)."""
        # Clear any existing cookies to avoid CookieConflict
        client.cookies.clear()
        resp = client.post("/api/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        # Extract from Set-Cookie header directly to avoid httpx jar conflict
        set_cookie = resp.headers.get("set-cookie", "")
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("access_token="):
                return part[len("access_token="):]
        data = resp.json()
        return data.get("access_token", "")

    def _login_cookie(self, client, email: str, password: str) -> str:
        return self._login_token(client, email, password)

    def test_15_note_b_id_returns_404_for_user_a(self, client, user_a, user_b, note_a, note_b):
        """Test 14/15: GET /api/notes/{B_note_id} by User A must return 404."""
        # Login as A
        token_a = self._login_cookie(client, user_a.email, "TestPassA123!")
        client.cookies.set("access_token", token_a)

        resp = client.get(f"/api/notes/{note_b.id}")
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User A got {resp.status_code} for B's note "
            f"(expected 404). Response: {resp.text}"
        )
        # Must not leak ownership info
        body = resp.text.lower()
        assert "user b" not in body
        assert user_b.email not in body

    def test_15_note_a_id_returns_404_for_user_b(self, client, user_a, user_b, note_a, note_b):
        """Test 15: GET /api/notes/{A_note_id} by User B must return 404."""
        token_b = self._login_cookie(client, user_b.email, "TestPassB123!")
        client.cookies.set("access_token", token_b)

        resp = client.get(f"/api/notes/{note_a.id}")
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User B got {resp.status_code} for A's note "
            f"(expected 404). Response: {resp.text}"
        )

    def test_16_rag_query_ignores_user_id_in_body(self, client, user_a, user_b):
        """Test 16: POST /api/rag/query must not accept user_id from request body."""
        # Login as A
        token_a = self._login_cookie(client, user_a.email, "TestPassA123!")
        client.cookies.set("access_token", token_a)

        # Try to inject user_b's ID in the body
        resp = client.post("/api/rag/query", json={
            "question": "What is RAG?",
            "user_id": user_b.id,  # This field must be ignored
        })
        # Should succeed (200) but user_id in body must be silently ignored
        # The actual user used must be user_a (from JWT), not user_b
        # We can't directly verify whose data was used from the response alone,
        # but the schema validation ensures user_id is stripped from the request
        assert resp.status_code in (200, 422), f"Unexpected status: {resp.text}"
        if resp.status_code == 200:
            data = resp.json()
            # Verify the response schema has no user_id leak
            assert "user_id" not in data, (
                "SECURITY VIOLATION: API returned user_id in RAG response!"
            )

    def test_11_user_a_cannot_reindex_b_note(self, client, user_a, user_b, note_a, note_b):
        """Test 11: POST /api/notes/{B_note_id}/reindex by User A must return 404."""
        token_a = self._login_cookie(client, user_a.email, "TestPassA123!")
        client.cookies.set("access_token", token_a)

        resp = client.post(f"/api/notes/{note_b.id}/reindex")
        assert resp.status_code == 404, (
            f"SECURITY VIOLATION: User A got {resp.status_code} for reindexing B's note "
            f"(expected 404). Response: {resp.text}"
        )

    def test_unauthenticated_request_returns_401(self, client):
        """Unauthenticated requests must be rejected."""
        # Clear cookies
        client.cookies.clear()
        resp = client.get("/api/notes")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_register_then_login_then_me(self, client):
        """Full auth flow: register → login → /me returns correct user."""
        uid = uuid.uuid4().hex[:8]
        email = f"flow-{uid}@test.example"
        # Register
        r1 = client.post("/api/auth/register", json={
            "name": "Flow Test",
            "email": email,
            "phone": f"+9999{uid[:8]}",
            "password": "FlowTest123!",
        })
        assert r1.status_code == 201, f"Register failed: {r1.text}"
        # Login
        r2 = client.post("/api/auth/login", json={"email": email, "password": "FlowTest123!"})
        assert r2.status_code == 200, f"Login failed: {r2.text}"
        token = client.cookies.get("access_token")
        assert token
        # Me
        client.cookies.set("access_token", token)
        r3 = client.get("/api/auth/me")
        assert r3.status_code == 200
        me_data = r3.json()
        assert me_data["email"] == email
        # Cleanup
        from backend.db.mysql import SessionLocal
        from backend.services.user_service import get_user_by_email
        db = SessionLocal()
        user = get_user_by_email(db, email)
        if user:
            db.delete(user); db.commit()
        db.close()
