---
title: Knowledge Graph
tags: [knowledge-graph, graph, relationships]
---

# Knowledge Graph

A knowledge graph is a structured representation of information as a network of entities (nodes) and relationships (edges). It explicitly encodes the relationships between concepts.

## Structure

A knowledge graph consists of:
- **Nodes** — Entities such as concepts, documents, people, or events
- **Edges** — Named, directed relationships between nodes
- **Properties** — Attributes on nodes and edges

For example:
```
(RAG) -[:USES]-> (Embeddings)
(RAG) -[:USES]-> (Vector_Search)
(Vector_Search) -[:USES]-> (Vector_Database)
(Vector_Database) -[:STORES]-> (Embeddings)
```

## Why Knowledge Graphs Matter

Traditional databases store facts in tables, losing the relational context. Knowledge graphs make relationships first-class citizens, enabling:
- **Multi-hop reasoning** — Following chains of relationships
- **Relationship-aware retrieval** — Finding information via connection paths
- **Explainability** — Showing why results are related

## Knowledge Graphs vs Vector Search

| Feature | Vector Search | Knowledge Graph |
|---|---|---|
| Finds similar content | ✅ | ❌ |
| Follows explicit relationships | ❌ | ✅ |
| Multi-hop reasoning | ❌ | ✅ |
| Structured queries | Limited | Full |

[[GraphRAG]] combines both to get the benefits of each.

## This Project's Graph Schema

This project uses the following node types:
- `(:Note)` — Represents an Obsidian markdown file
- `(:Chunk)` — A text chunk from a note (what gets embedded)
- `(:Concept)` — A named concept extracted from wiki-links

Relationship types include:
- `[:HAS_CHUNK]` — Note contains Chunk
- `[:MENTIONS]` — Chunk mentions Concept
- `[:LINKS_TO]` — Note wiki-links to another Note
- `[:USES]`, `[:DEPENDS_ON]`, `[:ENABLES]`, `[:RELATED_TO]` — Concept relationships

## Related

- [[Neo4j]] — The graph database implementing this knowledge graph
- [[GraphRAG]] — Retrieval pattern that leverages knowledge graphs
- [[RAG]] — The retrieval pattern that GraphRAG extends
- [[AI]] — The domain this knowledge graph represents
