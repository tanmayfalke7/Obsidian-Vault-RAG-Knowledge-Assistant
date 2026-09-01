---
title: Vector Database
tags: [vector-database, storage, search]
---

# Vector Database

A vector database is a specialised data store designed to store, index, and efficiently search high-dimensional [[Embeddings|embedding vectors]].

## Core Capabilities

Vector databases provide:
- **Storage** — Persisting embedding vectors alongside metadata
- **Indexing** — Approximate nearest-neighbour (ANN) index structures (HNSW, IVF, etc.)
- **Similarity Search** — Finding the K most similar vectors to a query vector
- **Filtering** — Combining vector search with metadata filters

## Similarity Metrics

Common similarity metrics:
- **Cosine similarity** — Angle between vectors (most common for text embeddings)
- **Dot product** — Related to cosine similarity when vectors are normalised
- **Euclidean distance** — Absolute distance in vector space

This project uses cosine similarity.

## Neo4j as a Vector Database

In this project, [[Neo4j]] serves as the vector database. [[Neo4j]] provides native vector indexing on node properties, eliminating the need for a separate vector store like ChromaDB or Pinecone.

Benefits of this approach:
1. A single database handles both graph relationships and vector search
2. Vector search results can be immediately expanded via graph traversal
3. No data synchronisation between separate systems
4. Simplified architecture

## The Vector Index

A vector index is created on the `embedding` property of `Chunk` nodes:

```cypher
CREATE VECTOR INDEX chunk_embedding_index
FOR (c:Chunk) ON (c.embedding)
OPTIONS { indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}}
```

## Related

- [[Embeddings]] — The vectors stored in vector databases
- [[Vector_Search]] — The search operation performed against vector databases
- [[Neo4j]] — The database providing vector capabilities in this project
- [[RAG]] — Uses vector databases as the retrieval store
- [[GraphRAG]] — Combines vector database search with graph traversal
