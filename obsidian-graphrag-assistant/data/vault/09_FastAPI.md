---
title: FastAPI
tags: [fastapi, backend, api, python]
---

# FastAPI

FastAPI is a modern, high-performance [[Python]] web framework for building REST APIs. It is used in this project as the backend API layer between the [[Streamlit]] frontend and the GraphRAG services.

## Key Features

- **Automatic OpenAPI docs** — Interactive Swagger UI at `/docs`
- **Type safety** — Request and response validation via [[Pydantic]]
- **Async support** — Built on Starlette and asyncio
- **Dependency injection** — Clean service wiring with `Depends()`
- **High performance** — Comparable to NodeJS and Go

## Project API Endpoints

This project exposes:

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Connection status for Neo4j and Gemini |
| POST | `/api/query` | Ask a question, get GraphRAG answer |
| POST | `/api/ingest` | Trigger vault re-ingestion |
| GET | `/api/sources` | List all notes in the knowledge base |
| GET | `/api/graph/{concept}` | Get graph neighbours of a concept |
| GET | `/api/stats` | Database statistics |

## Architecture in This Project

```
Streamlit Frontend
      ↓ HTTP (httpx)
FastAPI (port 8000)
      ↓
RAG Services
      ↓
Neo4j + Gemini
```

Streamlit calls FastAPI's `/api/query` endpoint. FastAPI orchestrates the retrieval pipeline and returns the structured response. This keeps the frontend thin and the logic server-side.

## Related

- [[Python]] — FastAPI is built with Python
- [[Streamlit]] — The frontend that calls FastAPI
- [[RAG]] — The backend logic FastAPI exposes
- [[GraphRAG]] — The advanced retrieval FastAPI orchestrates
