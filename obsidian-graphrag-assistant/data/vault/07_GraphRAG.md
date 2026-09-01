---
title: GraphRAG
tags: [graphrag, graph, rag, retrieval]
---

# GraphRAG

GraphRAG is an advanced retrieval pattern that combines the semantic retrieval power of [[RAG]] with the structured relationship traversal of [[Knowledge_Graph|knowledge graphs]].

## Why GraphRAG?

Standard [[RAG]] has a key limitation: it treats each document chunk independently. It can retrieve chunks that are semantically similar to a query, but it cannot follow explicit relationships between concepts.

Consider this question: *"What concept connects RAG to semantic search?"*

Standard RAG might retrieve the RAG document and the Semantic Search document, but it cannot answer the traversal question: RAG → uses → Embeddings → enables → Semantic Search.

GraphRAG solves this by using the knowledge graph to expand retrieved content with related nodes.

## How GraphRAG Works

1. **Vector Search** — Embed the query and find the most similar `Chunk` nodes using [[Vector_Search]]
2. **Graph Entry Points** — The matched chunks are entry points into the knowledge graph
3. **Graph Traversal** — Traverse relationships from each entry point to discover related concepts, notes, and paths
4. **Context Fusion** — Combine the retrieved chunks and graph context into a unified context string
5. **LLM Generation** — Send the fused context to the [[LLM]] to generate a grounded answer

## The GraphRAG Retrieval Path

```
User Question
     ↓
Gemini Embedding
     ↓
Neo4j Vector Search   ←── finds semantically similar chunks
     ↓
Top-K Chunks
     ↓
Graph Traversal       ←── expands to related concepts
     ↓
Concepts + Relationships
     ↓
Context Builder       ←── fuses text + graph context
     ↓
Gemini LLM
     ↓
Answer + Sources + Relationships
```

## Multi-hop Example

Question: *"How does GraphRAG build upon vector retrieval?"*

Graph path discovered:
```
GraphRAG -[:EXTENDS]-> RAG -[:USES]-> Vector_Search -[:USES]-> Vector_Database
```

The system can follow this path and include all intermediate nodes in the context.

## Implementation in This Project

This project implements GraphRAG using:
- [[Neo4j]] — Single database for both graph and vector storage
- [[Embeddings]] from Gemini — For semantic matching
- Cypher queries — For graph traversal
- The `neo4j-graphrag` Python package — For retriever abstractions

## Related

- [[RAG]] — The foundation that GraphRAG extends
- [[Knowledge_Graph]] — Provides the graph structure
- [[Vector_Search]] — The first step in GraphRAG retrieval
- [[Neo4j]] — The database implementing both capabilities
- [[Embeddings]] — Used for the vector search step
