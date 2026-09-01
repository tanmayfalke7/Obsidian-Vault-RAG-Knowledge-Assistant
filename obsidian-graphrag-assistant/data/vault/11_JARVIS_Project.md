---
title: JARVIS Project
tags: [jarvis, project, ai-assistant]
---

# JARVIS Project

JARVIS is a personal AI assistant project built to demonstrate how a [[LLM|Large Language Model]] can interact with external tools and knowledge sources to perform complex tasks.

## What JARVIS Does

JARVIS is designed to:
- Understand natural language instructions
- Use tools to take actions (search, retrieve, compute)
- Maintain conversational context
- Access external knowledge bases

## Technology Stack

JARVIS is built using:
- [[Python]] — Core language
- [[LLM]] — Language model for understanding and generation
- [[MCP]] — Model Context Protocol for tool integration

## MCP Integration

The [[MCP|Model Context Protocol]] (MCP) is a standard for connecting LLMs to external tools and data sources. JARVIS uses MCP to:
- Connect to file systems
- Query databases
- Call external APIs
- Use memory and retrieval tools

## Relationship to This Knowledge Base

The Obsidian GraphRAG Knowledge Assistant project is inspired by JARVIS. Where JARVIS uses MCP for tool access, this project uses [[GraphRAG]] with [[Neo4j]] for knowledge retrieval.

Both projects demonstrate how LLMs can be grounded with external knowledge to move beyond their training data.

## Related

- [[LLM]] — The core AI component
- [[Python]] — The implementation language
- [[MCP]] — Tool integration protocol
- [[RAG]] — Knowledge retrieval pattern used by AI assistants
- [[GraphRAG]] — Advanced retrieval used in knowledge-based assistants
