# API Reference

Base URL: `http://localhost:8000`

Authentication: JWT stored in HTTP-only `access_token` cookie.  
**user_id is NEVER accepted from the client — it comes from the JWT only.**

---

## Authentication

### POST /api/auth/register
Register a new account.

**Request:**
```json
{"name": "Jane Smith", "email": "jane@co.com", "phone": "+15551234567", "password": "Secret123!"}
```
**Response:** `201 Created` → `UserResponse`

---

### POST /api/auth/login
Login and receive a JWT cookie.

**Request:** `{"email": "jane@co.com", "password": "Secret123!"}`  
**Response:** `200 OK` → Sets `access_token` HTTP-only cookie + `TokenResponse`

---

### POST /api/auth/logout
Clear the JWT cookie.

---

### GET /api/auth/me
Return the authenticated user.  
**Response:** `UserResponse`

---

## Notes

### GET /api/notes
List notes with pagination and filtering.

**Query params:**
| Param        | Type    | Default      | Description                              |
|--------------|---------|--------------|------------------------------------------|
| `folder_id`  | string  | —            | Filter by folder (omit for unfiled)      |
| `all_folders`| bool    | false        | Return all folders' notes                |
| `search`     | string  | —            | Search title/filename/content            |
| `sort`       | string  | `updated_at` | `created_at | updated_at | title`        |
| `order`      | string  | `desc`       | `asc | desc`                             |
| `page`       | int     | 1            |                                          |
| `page_size`  | int     | 20           | Max 100                                  |

**Response:** `NoteListPage` `{items, total, page, page_size, pages}`

---

### POST /api/notes
Create a note and index it in Neo4j.

**Request:** `NoteCreateRequest` `{title, content, filename?, folder_id?}`  
**Response:** `201` → `NoteResponse`

---

### GET /api/notes/{note_id}
Get a note with full content.  
**Response:** `NoteResponse` | `404`

---

### PUT /api/notes/{note_id}
Update title, content, or folder. Re-indexes in Neo4j if content changes.  
**Request:** `NoteUpdateRequest` `{title?, content?, folder_id?}`

---

### PATCH /api/notes/{note_id}/move
Move a note to a different folder.  
**Request:** `NoteMoveRequest` `{folder_id?}` (null = unfiled)

---

### DELETE /api/notes/{note_id}
Delete from MySQL and Neo4j. Returns `204`.

---

### POST /api/notes/upload
Upload a `.md` file.  
**Form fields:** `file` (multipart), `folder_id?`, `title?`  
**Response:** `UploadResponse` `{note_id, title, filename, ingested, chunks_created, errors}`  
**Errors:** `422` for non-.md files, `413` if over `MAX_MARKDOWN_FILE_SIZE_MB`

---

### POST /api/notes/{note_id}/reindex
Re-run Neo4j ingestion using current MySQL content.  
**Response:** `IngestStatusResponse`

---

## Folders

### GET /api/folders/tree
Full nested folder tree.  
**Response:** `list[FolderTreeNode]` `{id, name, children, note_count}`

---

### GET /api/folders
List folders at one level. `?parent_id=<id>` for children; omit for root.

---

### POST /api/folders
Create folder. `{name, parent_id?}`  
**Errors:** `409 Conflict` if duplicate name at same level.

---

### GET /api/folders/{folder_id}
Folder with children and note count.

---

### PUT /api/folders/{folder_id}
Rename or move a folder. `{name?, parent_id?, move_to_root?}`  
**Errors:** `400` for cycle detection; `409` for duplicate name.

---

### DELETE /api/folders/{folder_id}
`?recursive=true` — deletes folder tree, unlinks notes (preserves them).  
Default: fails with `409` if folder is non-empty.

---

### GET /api/folders/{folder_id}/notes
Notes in a specific folder.

---

## Search

### GET /api/search?q=...
Full-text search over the authenticated user's notes.

**Query params:** `q` (required), `limit` (default 50, max 200)

**Response:**
```json
{
  "query": "RAG",
  "results": [
    {
      "id": "...", "title": "...", "filename": "...",
      "snippet": "...RAG combines retrieval...",
      "match_field": "content",
      "updated_at": "..."
    }
  ],
  "total": 3
}
```

Results are ranked: title > filename > content match.

---

## GraphRAG

### POST /api/rag/query
Ask a question over all the user's notes.

**Request:** `{"question": "How are embeddings related to vector search?", "top_k": 5}`  
**Note:** `user_id` must NOT be in the request. It comes from the JWT.

**Response:**
```json
{
  "answer": "Embeddings enable vector search by...",
  "sources": [
    {"note_id": "...", "title": "...", "filename": "...", "chunk_id": "...", "score": 0.91}
  ],
  "retrieved_chunks": [
    {"chunk_id": "...", "text": "...", "score": 0.91, "note_filename": "..."}
  ],
  "concepts": ["Embeddings", "Vector Search", "RAG"],
  "relationships": [
    {"source": "Embeddings", "relationship": "ENABLES", "target": "Vector Search"}
  ],
  "chunks_used": 3,
  "has_error": false
}
```

---

### POST /api/rag/note/{note_id}/query
Ask a question scoped to one specific note.

**Request:** `{"question": "What technologies are discussed in this note?"}`  
**Returns:** Same as `/api/rag/query`.  
**Errors:** `404` if note not found or belongs to another user.

---

### GET /api/rag/note/{note_id}/related
Notes and concepts related to this note via shared concepts.

**Query:** `?max_notes=5`

**Response:**
```json
{
  "note_id": "...",
  "related_notes": [{"note_id": "...", "title": "...", "shared_concepts": 3}],
  "concepts": [{"name": "RAG"}, {"name": "Embeddings"}],
  "relationships": [{"source": "RAG", "relationship": "USES", "target": "Embeddings"}]
}
```

---

## Graph Explorer

All graph endpoints are user-scoped. `user_id` is never accepted from the client.

### GET /api/graph/note/{note_id}
Graph centred on a note. Returns nodes (note + concepts) and edges.

**Query:** `?max_nodes=100`

**Response:**
```json
{
  "nodes": [
    {"id": "...", "label": "My Note", "type": "note", "is_root": false},
    {"id": "...", "label": "RAG", "type": "concept", "is_root": false}
  ],
  "edges": [
    {"source": "...", "target": "...", "type": "USES"}
  ]
}
```

---

### GET /api/graph/concept/{concept_id}
Graph centred on a concept.

**Query:** `?depth=2&max_nodes=100`  
**Note:** `concept_id` format is `{user_id}:concept:{slug}`. The endpoint verifies user ownership.

**Response:** Same `{nodes, edges}` format.

---

### GET /api/graph/neighbors/{concept_id}
Immediate 1-hop neighbours of a concept.

**Response:**
```json
{
  "concept_id": "...",
  "name": "RAG",
  "outgoing": [
    {"id": "...", "name": "Embeddings", "relationship": "USES", "direction": "outgoing"}
  ],
  "incoming": [
    {"id": "...", "name": "GraphRAG", "relationship": "EXTENDS", "direction": "incoming"}
  ]
}
```

---

### GET /api/graph/path?source=RAG&target=Semantic+Search
Find the shortest concept path.

**Query:** `?source=RAG&target=Semantic+Search&max_depth=4`

**Response:**
```json
{
  "source": "RAG",
  "target": "Semantic Search",
  "found": true,
  "steps": [
    {"node": "RAG", "type": "Concept"},
    {"relationship": "USES"},
    {"node": "Embeddings", "type": "Concept"},
    {"relationship": "ENABLES"},
    {"node": "Semantic Search", "type": "Concept"}
  ]
}
```

---

## Users

### GET /api/users/me
Profile alias.

### GET /api/users/me/stats
Usage statistics: `{user_id, name, notes_count, is_active}`

---

## Health

### GET /health
```json
{"status": "ok", "mysql": "connected", "neo4j": "connected", "groq": "configured"}
```

---

## HTTP Status Codes

| Code | Meaning                                         |
|------|-------------------------------------------------|
| 200  | Success                                         |
| 201  | Created                                         |
| 204  | Deleted (no body)                               |
| 400  | Invalid request (e.g. empty name, bad parent)  |
| 401  | Unauthenticated                                 |
| 404  | Not found / not owned by this user              |
| 409  | Conflict (duplicate folder, non-empty delete)   |
| 413  | File too large                                  |
| 422  | Validation error                                |
| 503  | Graph/LLM service unavailable                   |

**Note:** The API always returns `404` (not `403`) for resources that exist but belong to another user. This prevents information leakage about other tenants.
