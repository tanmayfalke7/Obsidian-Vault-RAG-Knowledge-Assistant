"""Focused backend hardening regression tests."""
from __future__ import annotations

import pytest
from fastapi import Response


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../evil.md", "evil.md"),
        ("....\\evil.md", "evil.md"),
        ("/etc/passwd.md", "passwd.md"),
        ("notes/hello world.md", "hello world.md"),
    ],
)
def test_upload_filename_is_sanitized_to_safe_basename(raw, expected):
    from backend.core.validation import sanitize_markdown_filename

    assert sanitize_markdown_filename(raw) == expected


@pytest.mark.parametrize("raw", ["CON.md", "notes.txt", "..."])
def test_upload_filename_rejects_unsafe_names(raw):
    from backend.core.validation import sanitize_markdown_filename

    with pytest.raises(ValueError):
        sanitize_markdown_filename(raw)


def test_login_response_does_not_expose_token(monkeypatch):
    from backend.api import auth_routes
    from backend.schemas import LoginRequest

    monkeypatch.setattr(auth_routes, "login_user", lambda db, email, password: "signed.jwt")

    response = Response()
    result = auth_routes.login(
        LoginRequest(email="user@example.com", password="Password123"),
        response,
        None,
        None,
    )

    assert result.model_dump() == {"detail": "Logged in"}
    assert "signed.jwt" not in str(result.model_dump())
    assert "httponly" in response.headers["set-cookie"].lower()


def test_rag_request_rejects_user_id_smuggling():
    from pydantic import ValidationError
    from backend.schemas import RAGQueryRequest

    with pytest.raises(ValidationError):
        RAGQueryRequest(question="What is RAG?", user_id="other-user")


def test_graph_traversal_depth_is_bounded(monkeypatch):
    from backend.services import retrieval_service

    captured: dict[str, object] = {}

    def fake_run_query(cypher, parameters=None, database="neo4j"):
        captured["cypher"] = cypher
        captured["parameters"] = parameters or {}
        return []

    monkeypatch.setattr(retrieval_service, "run_query", fake_run_query)

    retrieval_service.expand_graph_from_chunks(
        chunk_ids=["u:n:chunk:0"],
        user_id="u",
        hops=100000,
        database="neo4j",
        max_rels=100000,
    )

    assert "[rel*1..4]" in captured["cypher"]
    assert captured["parameters"]["max_rels"] == 100


def test_vector_search_bounds_top_k_and_candidate_pool(monkeypatch):
    from backend.services import retrieval_service

    captured: dict[str, object] = {}

    def fake_run_query(cypher, parameters=None, database="neo4j"):
        captured["parameters"] = parameters or {}
        return []

    monkeypatch.setattr(retrieval_service, "run_query", fake_run_query)

    retrieval_service.vector_search(
        query_embedding=[0.1, 0.2],
        user_id="u",
        top_k=1000000,
        index_name="chunk_embedding_index",
        database="neo4j",
    )

    assert captured["parameters"]["top_k"] == 20
    assert captured["parameters"]["candidate_k"] <= 500
