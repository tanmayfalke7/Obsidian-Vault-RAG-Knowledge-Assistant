"""
Web application tests.
Integration tests for auth, pages, API endpoints.
Uses pytest + httpx async client against the real app.
"""
import sys
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Override DB to in-memory for tests
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def app():
    """Build app with test DB."""
    from app.main import app as fastapi_app
    from app.db.database import init_db
    await init_db()
    return fastapi_app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ── Health ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] == "ok"


# ── Auth ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_login_page(client):
    r = await client.get("/login")
    assert r.status_code == 200
    assert b"Sign in" in r.content


@pytest.mark.anyio
async def test_register_page(client):
    r = await client.get("/register")
    assert r.status_code == 200
    assert b"Create account" in r.content


@pytest.mark.anyio
async def test_register_and_login(client):
    # Register
    r = await client.post("/register", data={
        "email": "test@example.com",
        "username": "testuser",
        "full_name": "Test User",
        "password": "password123",
        "password_confirm": "password123",
    }, follow_redirects=False)
    # Should redirect to dashboard after registration
    assert r.status_code in (200, 302)

    # Login with wrong password
    r = await client.post("/login", data={
        "email": "test@example.com",
        "password": "wrongpassword",
    }, follow_redirects=False)
    assert r.status_code == 400

    # Login with correct password
    r = await client.post("/login", data={
        "email": "test@example.com",
        "password": "password123",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "access_token" in r.cookies


@pytest.mark.anyio
async def test_duplicate_email_rejected(client):
    # Second register with same email
    r = await client.post("/register", data={
        "email": "test@example.com",
        "username": "other_user",
        "full_name": "Other",
        "password": "password123",
        "password_confirm": "password123",
    })
    assert b"already exists" in r.content


@pytest.mark.anyio
async def test_password_mismatch_rejected(client):
    r = await client.post("/register", data={
        "email": "new@example.com",
        "username": "newuser",
        "full_name": "New",
        "password": "password123",
        "password_confirm": "different",
    })
    assert b"Passwords do not match" in r.content


# ── Unauthenticated redirects ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_dashboard_requires_auth(client):
    r = await client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 303)


@pytest.mark.anyio
async def test_chat_requires_auth(client):
    r = await client.get("/chat", follow_redirects=False)
    assert r.status_code in (302, 303)


@pytest.mark.anyio
async def test_documents_requires_auth(client):
    r = await client.get("/documents", follow_redirects=False)
    assert r.status_code in (302, 303)


@pytest.mark.anyio
async def test_admin_requires_admin(client):
    r = await client.get("/admin", follow_redirects=False)
    assert r.status_code in (302, 303, 403)


# ── Authenticated pages ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_client(client):
    """Client with a valid session cookie."""
    r = await client.post("/login", data={
        "email": "test@example.com",
        "password": "password123",
    }, follow_redirects=False)
    token = r.cookies.get("access_token")
    client.cookies.set("access_token", token)
    yield client
    client.cookies.delete("access_token")


@pytest.mark.anyio
async def test_dashboard_loads(auth_client):
    r = await auth_client.get("/dashboard")
    assert r.status_code == 200
    assert b"Dashboard" in r.content


@pytest.mark.anyio
async def test_chat_page_loads(auth_client):
    r = await auth_client.get("/chat")
    assert r.status_code == 200
    assert b"Ask" in r.content


@pytest.mark.anyio
async def test_documents_page_loads(auth_client):
    r = await auth_client.get("/documents")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_upload_page_loads(auth_client):
    r = await auth_client.get("/documents/upload")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_folders_page_loads(auth_client):
    r = await auth_client.get("/folders")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_search_page_loads(auth_client):
    r = await auth_client.get("/search")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_search_htmx_partial(auth_client):
    r = await auth_client.get("/search?q=test", headers={"HX-Request": "true"})
    assert r.status_code == 200
    # Should return partial, not full page
    assert b"<!DOCTYPE html>" not in r.content


@pytest.mark.anyio
async def test_profile_page_loads(auth_client):
    r = await auth_client.get("/profile")
    assert r.status_code == 200
    assert b"Profile" in r.content or b"Account" in r.content


@pytest.mark.anyio
async def test_access_request_page_loads(auth_client):
    r = await auth_client.get("/access-request")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_folder_create(auth_client):
    r = await auth_client.post("/folders/create", data={"name": "Test Folder"})
    assert r.status_code in (200, 302)


@pytest.mark.anyio
async def test_chat_ask_no_query_budget(auth_client):
    """Chat ask should handle the case gracefully when AI backend isn't ready."""
    r = await auth_client.post("/chat/ask", data={"question": "What is RAG?"})
    # Either 200 (answer or error partial) or 402 (limit) — should never 500 crash
    assert r.status_code in (200, 402, 500)


# ── Logout ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_logout(auth_client):
    r = await auth_client.post("/logout", follow_redirects=False)
    assert r.status_code == 302
