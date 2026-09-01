# Sample Cypher Queries

Useful queries for verifying and exploring the knowledge graph in Neo4j Browser or `cypher-shell`.

## 1. Node Counts

```cypher
MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC;
```

## 2. Project Node Counts Only

```cypher
MATCH (n {project: "obsidian-graphrag-assistant"})
RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC;
```

## 3. All Concept Relationships

```cypher
MATCH (a:Concept)-[r]->(b:Concept)
RETURN a.name AS source, type(r) AS relationship, b.name AS target
ORDER BY source, relationship;
```

## 4. Notes and Their Chunk Counts

```cypher
MATCH (n:Note)-[:HAS_CHUNK]->(c:Chunk)
RETURN n.title AS note, count(c) AS chunks
ORDER BY chunks DESC;
```

## 5. Chunks That Mention Specific Concepts

```cypher
MATCH (c:Chunk)-[:MENTIONS]->(concept:Concept)
RETURN c.id AS chunk_id, collect(concept.name) AS concepts
ORDER BY chunk_id;
```

## 6. Multi-hop: Find Path from RAG to Semantic Search

```cypher
MATCH path = (rag:Concept {name: "RAG"})-[*1..3]->(target:Concept {name: "Semantic Search"})
RETURN path;
```

## 7. Learning Path Traversal

```cypher
MATCH path = (python:Concept {name: "Python"})-[:PREREQUISITE_OF*1..8]->(end:Concept)
RETURN [node in nodes(path) | node.name] AS learning_path;
```

## 8. GraphRAG Neighbourhood

```cypher
MATCH (graphrag:Concept {name: "GraphRAG"})-[r]->(related:Concept)
RETURN graphrag.name AS concept, type(r) AS rel, related.name AS related_to;
```

## 9. Vector Index Status

```cypher
SHOW INDEXES YIELD name, state, type
WHERE type = "VECTOR"
RETURN name, state;
```

## 10. Check Embeddings Are Stored

```cypher
MATCH (c:Chunk)
WHERE c.embedding IS NOT NULL
RETURN count(c) AS chunks_with_embeddings;
```

## 11. Verify Vector Search Works (replace [...] with actual embedding)

```cypher
CALL db.index.vector.queryNodes('chunk_embedding_index', 5, $embedding)
YIELD node, score
RETURN node.text, score
ORDER BY score DESC;
```

## 12. All Relationships Between Notes

```cypher
MATCH (a:Note)-[r:LINKS_TO]->(b:Note)
RETURN a.title AS source, b.title AS target;
```

## 13. Concept Mentions Per Note

```cypher
MATCH (n:Note)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(concept:Concept)
RETURN n.title AS note, collect(DISTINCT concept.name) AS concepts_mentioned
ORDER BY note;
```

## 14. Find Concepts With Most Connections

```cypher
MATCH (c:Concept)-[r]-()
RETURN c.name AS concept, count(r) AS degree
ORDER BY degree DESC
LIMIT 10;
```

## 15. Full Schema Overview

```cypher
CALL db.schema.visualization();
```
