---
title: Learning Path
tags: [learning, roadmap, prerequisites]
---

# Learning Path

A recommended sequence for learning the concepts covered in this knowledge base, from foundations to advanced topics.

## The Path

```
Python
  ↓ (prerequisite for)
LLM
  ↓ (prerequisite for)
Embeddings
  ↓ (prerequisite for)
Vector Search
  ↓ (prerequisite for)
RAG
  ↓ (prerequisite for)
Knowledge Graph
  ↓ (prerequisite for)
GraphRAG
  ↓ (built on)
Neo4j
```

## Step by Step

### 1. [[Python]]
The programming language that ties everything together. Required for all tools and frameworks in this stack.

### 2. [[LLM]]
Understand how large language models work, their capabilities, and their limitations (especially the [[Context_Window]]).

### 3. [[Embeddings]]
Learn how text is converted into numerical vectors and why this enables semantic search.

### 4. [[Vector_Search]]
Understand approximate nearest-neighbour search and how embeddings enable finding similar content.

### 5. [[RAG]]
Learn the standard retrieval-augmented generation pipeline: embed → search → retrieve → generate.

### 6. [[Knowledge_Graph]]
Understand graph databases, nodes, relationships, and Cypher queries.

### 7. [[GraphRAG]]
Combine your RAG knowledge with graph traversal to build more powerful, multi-hop retrieval systems.

### 8. [[Neo4j]]
The practical implementation: learn Neo4j as the unified graph + vector database.

## Why This Order?

Each step builds on the previous:
- You cannot understand RAG without understanding embeddings
- You cannot understand GraphRAG without understanding both RAG and knowledge graphs
- Neo4j is the practical tool for implementing GraphRAG

This note demonstrates multi-hop reasoning. The learning path encodes prerequisite relationships that can be traversed: Python → LLM → Embeddings → Vector_Search → RAG → Knowledge_Graph → GraphRAG.
