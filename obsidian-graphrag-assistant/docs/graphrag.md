# GraphRAG Architecture

## Overview

The system uses **GraphRAG** — combining vector similarity search with knowledge graph traversal to answer questions grounded in the user's own notes.

```
Question
  │
  ▼
Query Embedding (fastembed, local, 384 dims)
  │
  ▼
User-Scoped Vector Search
  │  CALL db.index.vector.queryNodes(index, candidate_k, embedding)
  │  WHERE chunk.user_id = $user_id   ← DB-level, NOT Python post-filter
  │  LIMIT $top_k
  │
  ▼
Top-K Chunks (user's notes only)
  │
  ├── MENTIONS ──► Concepts (user-scoped)
  │                    │
  │                    └─ USES / ENABLES / EXTENDS ──► Related Concepts
  │
  ▼
Context Fusion
  │  RETRIEVED DOCUMENTS
  │  [Source: filename.md] (score: 0.91)
  │  <chunk text>
  │
  │  GRAPH RELATIONSHIPS
  │  RAG --[USES]--> Embeddings
  │
  ▼
Gemini LLM (gemini-3.8-flash)
  │  System: cite sources, no hallucination, trace graph relationships
  │
  ▼
Answer + Sources + Relationships + Retrieved Chunks
```

---

## Tenant Isolation

### The Problem

Multiple users share one Neo4j database and one vector index.  
Without isolation, User A's question could retrieve User B's chunks.

### The Solution: User-Scoped IDs + DB-Level Filtering

**Node IDs are deterministic and embed `user_id`:**

| Node    | ID format                              |
|---------|----------------------------------------|
| Note    | `{user_id}:{mysql_note_id}`            |
| Chunk   | `{user_id}:{mysql_note_id}:chunk:{i}`  |
| Concept | `{user_id}:concept:{normalized_name}`  |

**Every node carries `user_id` as a property.**

**Vector retrieval uses a database-level WHERE clause, not Python:**

```cypher
CALL db.index.vector.queryNodes($index_name, $candidate_k, $embedding)
YIELD node AS chunk, score
WHERE chunk.user_id = $user_id       ← applied BEFORE LIMIT
MATCH (n:Note {user_id: $user_id})-[:HAS_CHUNK]->(chunk)
RETURN chunk.id, chunk.text, score
ORDER BY score DESC
LIMIT $top_k
```

The candidate pool is `max(top_k × 10, 50)` to guarantee enough user-specific results even when other users occupy higher similarity positions.

**Graph traversal pins `user_id` on every node:**

```cypher
MATCH (chunk:Chunk {id: $cid, user_id: $user_id})
      -[:MENTIONS]->
      (concept:Concept {user_id: $user_id})
      -[*1..2]-
      (related:Concept {user_id: $user_id})
```

No path can escape a user's subgraph.

### The Mandatory Same-Concept Test

Two users can have a concept with the same name ("RAG"):

- User A's RAG USES Neo4j
- User B's RAG USES PostgreSQL

Because concept IDs embed `user_id`, these are completely separate nodes.  
User A asking "What does RAG use?" must never see PostgreSQL.  
This is verified by `tests/test_graphrag.py::TestMandatorySameConceptIsolation`.

---

## Vector Retrieval Strategy

### Why not use neo4j-graphrag's VectorCypherRetriever?

The installed `neo4j-graphrag==1.19.0` does not expose a direct user-scoped pre-filter in its `VectorCypherRetriever`. Its high-level API assumes a single-tenant or pre-filtered dataset.

We implement retrieval directly via raw Cypher (`db.index.vector.queryNodes`) with user_id filtering in the WHERE clause of the same query. This gives us:

1. **Database-level isolation** — the Neo4j engine applies the filter before returning results
2. **Correct top-K** — we get the top_k results from *this user's* corpus, not globally
3. **No information leakage** — even if another user's chunks score higher, they are excluded before LIMIT

### Candidate Pool

We query `candidate_k = max(top_k × 10, 50)` candidates from the index. After the user filter, we take `top_k`. This handles the case where the first N global results all belong to other users.

---

## Graph Expansion

After vector retrieval:

```
Chunk (user_id=A)
  └─ MENTIONS ──► Concept "RAG" (user_id=A)
                      ├─ USES ──► Concept "Embeddings" (user_id=A)
                      └─ EXTENDS ──► Concept "GraphRAG" (user_id=A)
```

The traversal depth is configurable (`GRAPH_HOPS=2` default).  
Every hop adds the constraint `user_id = $user_id`.

---

## Context Fusion

The context string sent to Gemini is structured:

```
RETRIEVED DOCUMENTS

[Source: 03_RAG.md] (score: 0.851)
RAG combines information retrieval with language model generation...

[Source: 07_GraphRAG.md] (score: 0.812)
GraphRAG extends RAG with knowledge graph traversal...

GRAPH RELATIONSHIPS

RAG --[USES]--> Embeddings
RAG --[EXTENDS]--> GraphRAG
Embeddings --[ENABLES]--> Vector Search
```

The LLM is instructed to cite sources, not hallucinate, and trace graph relationships step by step.

---

## Source Attribution

Every retrieved chunk carries:
- `chunk_id` — the unique Neo4j chunk identifier (embeds user_id)
- `note_id` — the Neo4j note identifier (embeds user_id)
- `note_title` — human-readable title from Neo4j
- `note_filename` — original filename
- `score` — cosine similarity score

Only chunks with `user_id = current_user.id` are ever included.

---

## Graph Explorer API

The graph explorer exposes the user's knowledge graph structure for frontend visualization.

### Frontend-Friendly Format

All graph responses use `{nodes, edges}`:

```json
{
  "nodes": [
    {"id": "...:concept:rag", "label": "RAG", "type": "concept", "is_root": true},
    {"id": "...:concept:embeddings", "label": "Embeddings", "type": "concept"}
  ],
  "edges": [
    {"source": "...:concept:rag", "target": "...:concept:embeddings", "type": "USES"}
  ]
}
```

### Size Limits

| Config             | Default | Description                     |
|--------------------|---------|----------------------------------|
| `GRAPH_MAX_NODES`  | 100     | Max nodes returned by explorer  |
| `GRAPH_MAX_DEPTH`  | 2       | Max traversal depth for paths   |
| `GRAPH_HOPS`       | 2       | Hops during RAG graph expansion |

---

## Failure Handling

| Failure              | Behavior                                                         |
|----------------------|------------------------------------------------------------------|
| No matching chunks   | Returns polite "no information" answer, empty sources           |
| Gemini LLM timeout   | Returns graceful error message, `has_error: true` in response   |
| Neo4j unavailable    | 503 Service Unavailable (graph endpoints)                       |
| Neo4j missing index  | Logged as error; vector search returns empty result             |
| Invalid concept ID   | 404 Not Found                                                    |
| Wrong user's note    | 404 Not Found (no information leakage)                          |
| Empty path           | `{"found": false, "steps": []}`                                 |

---

## Configuration

```env
# Vector retrieval
VECTOR_INDEX_NAME=chunk_embedding_index
EMBEDDING_DIMENSIONS=384
TOP_K=5
GRAPH_HOPS=2

# Graph explorer limits
GRAPH_MAX_NODES=100
GRAPH_MAX_DEPTH=2
```
