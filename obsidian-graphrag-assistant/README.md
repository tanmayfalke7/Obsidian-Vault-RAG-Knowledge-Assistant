# Obsidian Vault GraphRAG Knowledge Assistant

A multi-user, multi-tenant GraphRAG knowledge assistant backend.  
Users upload Markdown notes, which are ingested into a user-scoped Neo4j knowledge graph.  
Each user's vector search, graph traversal, and LLM answers are **strictly isolated** from every other user.

---

## Architecture

```
User (JWT cookie)
     ↓
FastAPI Authentication  ←── user_id NEVER accepted from client
     ↓
Authenticated user_id
     ↓
MySQL (users, folders, notes)  +  Neo4j (user-scoped graph + vector index)
     ↓
GraphRAG Retrieval (user-scoped vector search → graph traversal)
     ↓
Gemini LLM (grounded answer from user's own context only)
     ↓
Answer + Sources (user-owned notes only)
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| API Framework | FastAPI |
| Frontend | FastAPI static files + Jinja2 templates + HTML/CSS + vanilla JavaScript + HTMX |
| Application DB | MySQL 8.x (pymysql + SQLAlchemy) |
| Migrations | Alembic |
| Knowledge Graph | Neo4j 2026.x |
| Vector Index | Neo4j native vector index (cosine, 384 dims) |
| Embeddings | fastembed (BAAI/bge-small-en-v1.5, local, no API key) |
| LLM | Google Gemini API (gemini-3.8-flash) |
| Auth | JWT (HTTP-only cookie, argon2 password hashing) |

---

## Setup

### 1. Clone and enter the project

```powershell
cd obsidian-graphrag-assistant
```

### 2. Create virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill in real credentials (see Environment Variables below).  
**Never commit `.env`.**

---

## Environment Variables

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=notes_db
MYSQL_USERNAME=root
MYSQL_PASSWORD=your_mysql_password

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j

# Gemini LLM
GEMINI_API_KEY=your_gemini_api_key
GEMINI_LLM_MODEL=gemini-3.8-flash

# Embeddings (local, no API key)
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
VECTOR_INDEX_NAME=chunk_embedding_index

# Vector retrieval
TOP_K=5
GRAPH_HOPS=2

# JWT Auth
JWT_SECRET_KEY=your_64_char_hex_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# App
PROJECT_TAG=obsidian-graphrag-assistant
LOG_LEVEL=INFO
```

---

## Database Setup

### MySQL

```powershell
# Create the database
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS notes_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### Neo4j + MySQL — initialise schema

```powershell
.venv\Scripts\python.exe scripts\initialize_database.py
```

This creates:
- MySQL tables (users, folders, notes) via SQLAlchemy
- Neo4j uniqueness constraints for Note.id, Chunk.id, Concept.id, User.id
- Neo4j lookup indexes for user_id on all tenant-owned labels
- Neo4j vector index (chunk_embedding_index, 384 dims, cosine)

---

## Alembic Migrations

### Apply all migrations

```powershell
.venv\Scripts\alembic.exe upgrade head
```

### Rollback one step

```powershell
.venv\Scripts\alembic.exe downgrade -1
```

### Create a new migration after model changes

```powershell
.venv\Scripts\alembic.exe revision --autogenerate -m "describe your change"
.venv\Scripts\alembic.exe upgrade head
```

### View current migration state

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\alembic.exe history
```

---

## Running the Server

```powershell
.venv\Scripts\uvicorn backend.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- Web app: http://localhost:8000/

The FastAPI app is the only application entry point. The obsolete Streamlit entry point has been removed.

---

## API Endpoints

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Register (name, email, phone, password) |
| POST | `/api/auth/login` | Login → sets HTTP-only JWT cookie |
| POST | `/api/auth/logout` | Clear JWT cookie |
| GET | `/api/auth/me` | Current authenticated user |

### Notes (all user-scoped, no user_id in body)

| Method | Path | Description |
|---|---|---|
| GET | `/api/notes` | List user's notes |
| POST | `/api/notes` | Create note + ingest |
| GET | `/api/notes/{id}` | Get note (404 if not owned) |
| PUT | `/api/notes/{id}` | Update note + re-ingest |
| DELETE | `/api/notes/{id}` | Delete from MySQL + Neo4j |
| POST | `/api/notes/upload` | Upload `.md` file + ingest |
| POST | `/api/notes/{id}/reindex` | Re-run ingestion |

### Folders

| Method | Path | Description |
|---|---|---|
| GET | `/api/folders` | List user's folders |
| POST | `/api/folders` | Create folder |
| GET | `/api/folders/{id}` | Get folder |
| PUT | `/api/folders/{id}` | Rename folder |
| DELETE | `/api/folders/{id}` | Delete folder |
| GET | `/api/folders/{id}/notes` | List notes in folder |

### Search & RAG

| Method | Path | Description |
|---|---|---|
| GET | `/api/search?q=...` | Search user's notes (MySQL full-text) |
| POST | `/api/rag/query` | GraphRAG query (user-scoped) |

### Users

| Method | Path | Description |
|---|---|---|
| GET | `/api/users/me` | Profile alias |
| GET | `/api/users/me/stats` | Note count + usage |

### Frontend Pages

| Method | Path | Description |
|---|---|---|
| GET | `/` | Redirects to dashboard or login |
| GET | `/login` | Login page |
| GET | `/register` | Registration page |
| GET | `/dashboard` | Authenticated knowledge dashboard |
| GET | `/notes` | Notes workbench |
| GET | `/notes/{note_id}` | Notes workbench opened on a note |
| GET | `/graph` | Canvas graph explorer |
| GET | `/rag` | Global GraphRAG console |
| GET | `/settings` | Runtime and safety settings |

Protected pages redirect unauthenticated users to `/login`.

### Legacy JSON API

| Prefix | Description |
|---|---|
| `/api/v1/*` | Original single-user API (uses `user_id="system"`) |

---

## Frontend Structure

```
frontend/
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── settings.html
│   ├── auth/
│   │   ├── login.html
│   │   └── register.html
│   ├── graph/
│   │   └── explorer.html
│   ├── notes/
│   │   └── index.html
│   └── rag/
│       └── query.html
└── static/
    ├── css/
    │   ├── auth.css
    │   ├── components.css
    │   ├── editor.css
    │   ├── graph.css
    │   └── main.css
    └── js/
        ├── app.js
        ├── editor.js
        ├── graph.js
        ├── rag.js
        └── search.js
```

Implemented frontend workflows:
- Cookie-based registration, login, logout, validation, loading states, and API error messages.
- Dashboard stats, recent notes, upload entry point, search entry point, and GraphRAG entry point.
- Sidebar folder tree with expand/collapse, create, rename, recursive delete, and note filtering.
- Markdown note list, sorting, search, pagination controls, note create/open/save/delete/reindex, autosave, and sanitized live preview.
- Markdown upload dialog with `.md` validation, file metadata, indexing feedback, and post-upload note opening.
- Global GraphRAG page with answer, sources, concepts, relationships, retrieved chunks, and loading pipeline feedback.
- Note-scoped GraphRAG inspector with related notes, concepts, relationships, and source answer display.
- Canvas graph explorer using backend `/api/graph/*` endpoints only; JavaScript never talks to Neo4j directly.

HTMX is loaded by the base template for progressive enhancement, while the API-heavy editor, upload, graph, and GraphRAG flows use vanilla JavaScript against the JSON API.

---

## Ingesting the Sample Vault

```powershell
.venv\Scripts\python.exe scripts\ingest_vault.py --user-id system
```

This ingests all 13 sample Markdown notes for the `system` user.

---

## Testing

### Run all tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

### Run only isolation tests (most important)

```powershell
.venv\Scripts\python.exe -m pytest tests/test_isolation.py -v
```

### Run only parser tests (no services needed)

```powershell
.venv\Scripts\python.exe -m pytest tests/test_parser.py -v
```

### Test results summary

```
tests/test_isolation.py  — 27 passed  (multi-user isolation)
tests/test_parser.py     — 14 passed  (markdown parsing)
Total: 41 passed
```

---

## Multi-Tenant Isolation Design

### The Core Principle

`user_id` is **never accepted from the client**. It is always extracted from the validated JWT cookie:

```python
# ❌ WRONG — never do this
POST /api/rag/query { "user_id": "...", "question": "..." }

# ✅ CORRECT — always like this  
POST /api/rag/query { "question": "..." }
# user_id = current_user.id  (from JWT cookie, server-side only)
```

### MySQL Isolation

Every table has `user_id` as a foreign key. Every query includes `WHERE user_id = $user_id` — the database itself prevents cross-user access. A user guessing another user's note UUID gets `None` (mapped to 404) because the SQL query filters by their own ID.

### Neo4j Node IDs (Deterministic, User-Scoped)

```
note_id:    {user_id}:{mysql_note_id}
chunk_id:   {user_id}:{mysql_note_id}:chunk:{index}
concept_id: {user_id}:concept:{normalized_name}
```

This means `User A` and `User B` can both have a concept named "RAG" and they resolve to **completely different Neo4j nodes** with **different IDs**.

### Vector Retrieval Isolation

```cypher
CALL db.index.vector.queryNodes($index_name, $candidate_k, $embedding)
YIELD node AS chunk, score
WHERE chunk.user_id = $user_id          ← filter at DB level, NOT in Python
MATCH (n:Note {user_id: $user_id})-[:HAS_CHUNK]->(chunk)
...
LIMIT $top_k
```

The vector index is shared but **the WHERE clause filters by `user_id` before the LIMIT** — so other users' chunks never appear in results, even if they score higher. The candidate pool is 10× top_k to guarantee enough user-specific results.

### Graph Traversal Isolation

```cypher
MATCH (chunk:Chunk {id: $cid, user_id: $user_id})-[:MENTIONS]->(concept:Concept {user_id: $user_id})
MATCH (concept)-[rel*1..2]-(related:Concept {user_id: $user_id})
```

Every node in the traversal path is constrained to `user_id`. A path cannot cross into another user's concept graph.

---

## Files

### Created

```
backend/core/security.py          — JWT + argon2 password hashing
backend/core/dependencies.py      — get_current_user dependency
backend/db/mysql.py               — SQLAlchemy engine + session factory
backend/db/models/__init__.py     — Model registry
backend/db/models/user.py         — User ORM model
backend/db/models/folder.py       — Folder ORM model
backend/db/models/note.py         — Note ORM model
backend/schemas/__init__.py       — All Pydantic request/response schemas
backend/services/auth_service.py  — Registration, login, token management
backend/services/user_service.py  — User CRUD
backend/services/note_service.py  — Note CRUD (all user-scoped)
backend/services/folder_service.py — Folder CRUD (all user-scoped)
backend/api/auth_routes.py        — /api/auth/*
backend/api/note_routes.py        — /api/notes/*
backend/api/folder_routes.py      — /api/folders/*
backend/api/search_routes.py      — /api/search
backend/api/rag_routes.py         — /api/rag/query
backend/api/user_routes.py        — /api/users/me
alembic/env.py                    — Alembic config
alembic/script.py.mako            — Migration template
alembic/versions/47d4f6b00b85_initial.py — Initial migration
alembic.ini                       — Alembic settings
tests/test_isolation.py           — 27 multi-user isolation tests
```

### Modified

```
backend/core/config.py            — Added MySQL + JWT settings
backend/services/graph_service.py — user_id on all nodes/queries/constraints
backend/services/ingestion_service.py — user-scoped IDs and ingestion
backend/services/retrieval_service.py — user-scoped vector search + graph traversal
backend/services/rag_service.py   — ask(question, user_id) required
backend/api/routes.py             — legacy API compat with user_id="system"
backend/main.py                   — MySQL init, all routers mounted
scripts/ingest_vault.py           — --user-id argument added
scripts/initialize_database.py    — MySQL + Neo4j init
tests/test_embeddings.py          — Updated for fastembed (no Gemini)
tests/test_rag.py                 — Updated for Groq (no Gemini)
.env                              — MySQL + JWT variables added
.env.example                      — Updated placeholders
requirements.txt                  — pymysql, alembic, argon2, email-validator added
```
