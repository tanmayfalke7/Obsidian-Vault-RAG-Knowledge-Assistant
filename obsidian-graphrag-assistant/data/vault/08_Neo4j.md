---
title: Neo4j
tags: [neo4j, database, graph]
---

# Neo4j

Neo4j is a native graph database that stores data as nodes and relationships rather than tables and rows. It is the only database used in this project and handles both the knowledge graph and the vector index.

## Core Concepts

### Nodes
Nodes represent entities. In this project:
- `(:Note)` — A markdown file from the vault
- `(:Chunk)` — A text chunk of a note
- `(:Concept)` — An extracted concept

### Relationships
Relationships connect nodes with named, directed edges:
```cypher
(a:Concept)-[:USES]->(b:Concept)
(n:Note)-[:HAS_CHUNK]->(c:Chunk)
(c:Chunk)-[:MENTIONS]->(concept:Concept)
```

### Properties
Nodes and relationships can have properties:
```cypher
(:Chunk {
  id: "chunk-001",
  text: "...",
  embedding: [...],  // 768-dimensional vector
  note_id: "note-001"
})
```

## Cypher Query Language

Neo4j uses Cypher, a declarative graph query language:

```cypher
// Find all concepts that RAG uses
MATCH (rag:Concept {name: "RAG"})-[:USES]->(other:Concept)
RETURN other.name

// Find multi-hop paths
MATCH path = (rag:Concept {name: "RAG"})-[*1..2]->(target:Concept)
RETURN path
```

## Vector Index

Neo4j supports native vector indexing. This project creates an index on `Chunk.embedding`:

```cypher
CREATE VECTOR INDEX chunk_embedding_index
FOR (c:Chunk) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
}
```

Vector search query:
```cypher
CALL db.index.vector.queryNodes(
  'chunk_embedding_index', 5, $queryEmbedding
) YIELD node, score
RETURN node.text, node.note_id, score
```

## Why Neo4j Instead of a Separate Vector Database

Using Neo4j as the sole database:
1. **Eliminates synchronisation** — No need to keep a graph DB and vector DB in sync
2. **Enables hybrid queries** — Vector search results can immediately traverse graph edges
3. **Simplifies architecture** — Single connection, single consistency model
4. **Enables GraphRAG natively** — Vector similarity → graph traversal in one query

## Related

- [[Knowledge_Graph]] — The graph structure Neo4j implements
- [[Vector_Database]] — The vector storage capability Neo4j provides
- [[GraphRAG]] — The retrieval pattern powered by Neo4j
- [[RAG]] — Uses Neo4j for the retrieval step
