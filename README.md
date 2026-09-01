# Obsidian Vault GraphRAG Knowledge Assistant

A knowledge-management system that ingests an Obsidian-style markdown vault, builds a Neo4j knowledge graph with vector embeddings, and provides a GraphRAG-powered conversational interface using Gemini.

---

## Problem

Traditional RAG treats documents as independent text chunks:

```
Question → Vector Search → Relevant Text → LLM → Answer
```

This misses explicit relationships between concepts. It cannot answer questions like:
- "What is the path from RAG to semantic search?"
- "What are all the prerequisites for learning GraphRAG?"
- "How does GraphRAG build upon vector retrieval?"

---

## Solution

This project implements GraphRAG — combining semantic vector search with knowledge graph traversal:

```
Question
    ↓
Gemini Embedding (768 dims)
    ↓
Neo4j Vector Index Search        ← semantic similarity
    ↓
Top-K Matched Chunks             ← entry points into graph
    ↓
Graph Traversal (1-2 hops)       ← follows explicit relationships
    ↓
Related Concepts + Paths         ← context enrichment
    ↓
Context Fusion (text + graph)
    ↓
Gemini LLM
    ↓
Answer + Sources + Relationships
```

---

## Key Features

- **GraphRAG retrieval** — vector similarity + graph traversal in one pipeline
- **Neo4j as sole database** — knowledge graph and vector index in one place
- **Gemini embeddings** — 768-dim vectors from `gemini-embedding-001`
- **Gemini generation** — grounded answers from `gemini-2.0-flash`
- **Source attribution** — every answer cites retrieved notes
- **Graph relationships** — shows the concept connections used for retrieval
- **Multi-hop reasoning** — follows chains like `RAG → Embeddings → Semantic Search`
- **FastAPI backend** — clean REST API with automatic OpenAPI docs
- **Streamlit frontend** — chat interface with graph explorer
- **Graph explorer** — explore any concept's graph neighbourhood

---

## Why GraphRAG?

| Feature | Traditional RAG | GraphRAG (this project) |
|---|---|---|
| Semantic search | ✅ | ✅ |
| Multi-hop reasoning | ❌ | ✅ |
| Explicit relationships | ❌ | ✅ |
| Path traversal | ❌ | ✅ |
| Source attribution | ✅ | ✅ |
| Relationship explanation | ❌ | ✅ |

---

## Why Neo4j Instead of ChromaDB / Pinecone?

Using Neo4j as the **only** database:
1. Eliminates synchronisation between separate graph and vector databases
2. Vector search results can immediately traverse graph edges in the same query
3. Enables `VectorCypherRetriever` pattern — find chunks, then expand graph context
4. Single connection, single consistency model, simpler architecture

---

## Knowledge Graph Schema

```
(:Note {id, title, filename, content, project})
    │
    │ HAS_CHUNK
    ▼
(:Chunk {id, text, embedding[768], chunk_index, note_id, project})
    │
    │ MENTIONS
    ▼
(:Concept {id, name, type, project})
    │
    │ USES / ENABLES / DEPENDS_ON / EXTENDS / BUILT_WITH / ...
    ▼
(:Concept)
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Knowledge graph | Neo4j 6.x |
| Vector index | Neo4j vector index (native) |
| Embeddings | Gemini `gemini-embedding-001` |
| LLM generation | Gemini `gemini-2.0-flash` |
| Gemini SDK | `google-genai` |
| GraphRAG package | `neo4j-graphrag` 1.19 |
| Backend API | FastAPI + Uvicorn |
| Frontend | Streamlit |
| Config | pydantic-settings + python-dotenv |
| Language | Python 3.10+ |

---

## Project Structure

```
obsidian-graphrag-assistant/
├── .env                    ← local secrets (never committed)
├── .env.example            ← template
├── .gitignore
├── README.md
├── requirements.txt
├── pytest.ini
│
├── data/vault/             ← sample Obsidian markdown notes
│
├── backend/
│   ├── main.py             ← FastAPI app entry point
│   ├── api/routes.py       ← all API endpoints
│   ├── core/config.py      ← pydantic-settings config
│   ├── db/neo4j_client.py  ← driver singleton
│   ├── models/schemas.py   ← Pydantic request/response models
│   ├── services/
│   │   ├── embedding_service.py  ← Gemini embedding calls
│   │   ├── llm_service.py        ← Gemini generation
│   │   ├── graph_service.py      ← Neo4j CRUD
│   │   ├── ingestion_service.py  ← ingest pipeline
│   │   ├── retrieval_service.py  ← vector + graph retrieval
│   │   └── rag_service.py        ← orchestration
│   └── utils/markdown_parser.py  ← frontmatter + wiki-link parser
│
├── frontend/streamlit_app.py
│
├── scripts/
│   ├── test_neo4j.py
│   ├── initialize_database.py
│   ├── ingest_vault.py
│   ├── create_indexes.py
│   ├── test_retrieval.py
│   └── reset_project_data.py
│
├── tests/
│   ├── test_parser.py      ← unit tests (no credentials needed)
│   ├── test_neo4j.py       ← integration (Neo4j required)
│   ├── test_embeddings.py  ← integration (Gemini required)
│   └── test_rag.py         ← end-to-end (both required)
│
└── docs/
    ├── architecture.md
    └── sample_queries.md
```

---

## Setup

### Prerequisites

- Python 3.10+
- Neo4j Desktop or Neo4j Community Edition (running on `bolt://localhost:7687`)
- Google Gemini API key

### 1. Clone and enter the project

```powershell
cd obsidian-graphrag-assistant
```

### 2. Create virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks script execution, run:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment

Copy `.env.example` to `.env` and fill in your credentials:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_actual_password
NEO4J_DATABASE=neo4j
GEMINI_API_KEY=your_actual_gemini_key
```

---

## Neo4j Setup

1. Install Neo4j Desktop from https://neo4j.com/download/
2. Create a new project and database
3. Start the database
4. Note your password (set during database creation)

---

## Gemini Setup

1. Go to https://aistudio.google.com/apikey
2. Create an API key
3. Add it to `.env` as `GEMINI_API_KEY`

---

## Running the Project

### Step 1: Test Neo4j connectivity

```powershell
.venv\Scripts\python.exe scripts\test_neo4j.py
```

### Step 2: Initialise the database

```powershell
.venv\Scripts\python.exe scripts\initialize_database.py
```

### Step 3: Ingest the vault

```powershell
.venv\Scripts\python.exe scripts\ingest_vault.py
```

Expected output:
```
Notes processed:      13
Chunks created:       ~35
Concepts created:     ~22
Relationships created: ~80
Embeddings generated: ~35
```

### Step 4: Start FastAPI

```powershell
.venv\Scripts\uvicorn backend.main:app --reload
```

API docs available at: http://localhost:8000/docs

### Step 5: Start Streamlit

```powershell
.venv\Scripts\streamlit run frontend/streamlit_app.py
```

Open: http://localhost:8501

---

## Sample Questions

Try these in the chat interface:

1. "What is RAG?"
2. "How are embeddings related to vector search?"
3. "What is the relationship between vector search and vector databases?"
4. "How does GraphRAG improve traditional RAG?"
5. "What role does Neo4j play in this system?"
6. "What should I learn before GraphRAG?"
7. "How are RAG, embeddings, vector search and Neo4j connected?"
8. "Find the relationship path from RAG to semantic search."
9. "What technologies are used by the JARVIS project?"
10. "Explain the difference between RAG and GraphRAG."

---

## Testing

Run unit tests (no credentials required):

```powershell
.venv\Scripts\python.exe -m pytest tests/test_parser.py -v
```

Run all tests (requires Neo4j + Gemini):

```powershell
.venv\Scripts\python.exe -m pytest -v
```

---

## Reset Data

To wipe only this project's data from Neo4j (other data is untouched):

```powershell
.venv\Scripts\python.exe scripts\reset_project_data.py
```

---

## Limitations

- Sample vault is synthetic (12 notes, ~20 concepts)
- No authentication on the API
- Single-user, local deployment only
- Re-ingestion re-generates all embeddings (no incremental update)
- Graph hops limited to 2 by default (configurable via `GRAPH_HOPS`)

---

## Future Improvements

- Incremental ingestion (only update changed files)
- Real Obsidian vault support (any vault directory)
- Graph visualisation using pyvis or d3.js
- Streaming LLM responses
- Multi-user support with auth
- Hybrid search (BM25 + vector)
- Custom relationship extraction via LLM
