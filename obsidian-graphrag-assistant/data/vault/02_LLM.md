---
title: Large Language Models
tags: [llm, ai, generation]
---

# Large Language Models

Large Language Models (LLMs) are neural networks trained on vast amounts of text data that can generate, understand, and reason about natural language.

## How LLMs Work

LLMs are trained using self-supervised learning on internet-scale text corpora. They learn statistical patterns in language and can generalise to new tasks through in-context learning and [[Prompt_Engineering]].

## Key Constraint: Context Window

The [[Context_Window]] is the maximum number of tokens an LLM can process in a single inference call. Modern models range from 4K to 1M+ tokens, but processing very long contexts is expensive and quality may degrade.

This constraint motivates [[RAG]], which retrieves only the most relevant information rather than stuffing the entire knowledge base into the context.

## Applications

LLMs power many applications including:
- Conversational assistants like [[JARVIS_Project]]
- Code generation
- Question answering over private knowledge bases

## Relationship to RAG

[[RAG]] uses LLMs as the generation component. The retrieval step provides the LLM with relevant context, allowing it to generate grounded, accurate answers rather than relying solely on parametric memory.

## Embeddings

LLMs are also used to generate [[Embeddings]] — dense vector representations of text that capture semantic meaning. These embeddings are central to [[RAG]] and [[GraphRAG]] retrieval pipelines.

## Prompt Engineering

[[Prompt_Engineering]] is the practice of crafting inputs to LLMs to elicit desired behaviours. System prompts, few-shot examples, and chain-of-thought instructions are common techniques.
