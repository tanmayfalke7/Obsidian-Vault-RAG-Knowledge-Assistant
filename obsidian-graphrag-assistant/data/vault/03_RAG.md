---
title: Retrieval Augmented Generation
tags: [rag, retrieval, generation]
---

# Retrieval Augmented Generation

Retrieval Augmented Generation (RAG) is an architecture that combines information retrieval with language model generation to produce grounded, accurate answers from a knowledge base.

## The Problem RAG Solves

[[LLM|Large Language Models]] have fixed parametric knowledge from training. They cannot access up-to-date information, private documents, or specialised domain knowledge. RAG solves this by retrieving relevant information at query time and providing it as context to the LLM.

## The RAG Workflow

1. The user asks a question.
2. The question is converted into an [[Embeddings|embedding vector]] using an embedding model.
3. The embedding is used to perform [[Vector_Search]] against an [[Vector_Database|embedding store]].
4. The top-K most similar text chunks are retrieved.
5. The retrieved chunks are assembled into a context string.
6. The context is passed to the [[LLM]] along with the original question.
7. The LLM generates a grounded answer citing the retrieved sources.

## Key Components

- [[Embeddings]] — Convert text to searchable vectors
- [[Vector_Search]] — Find semantically similar content
- [[Vector_Database]] — Store and index embeddings
- [[Chunking]] — Split documents into retrievable pieces
- [[Retrieval]] — The process of finding relevant content
- [[Generation]] — The LLM step that produces the final answer
- [[LLM]] — The language model that generates answers

## Limitation: Flat Retrieval

Standard RAG treats documents as independent. It cannot follow relationships between concepts. For example, it cannot answer "What concept connects RAG to semantic search?" because that requires traversing a relationship chain.

[[GraphRAG]] extends RAG with knowledge graph traversal to overcome this limitation.

## Related

- [[GraphRAG]] — Graph-enhanced version of RAG
- [[Chunking]] — Strategy for splitting documents
- [[Semantic_Search]] — Retrieval based on meaning rather than keywords
