"""
RAG service — USER-SCOPED GraphRAG orchestration.

user_id is REQUIRED on every call.
The LLM never receives context belonging to another user.
No chat history is persisted.

Pipeline:
  retrieve(question, user_id) → user-scoped chunks + graph context
  _build_context(result)      → structured context string (LLM input)
  generate_answer(q, context) → grounded LLM answer
  return RAGAnswer             → answer + sources + relationships + chunks
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.services.retrieval_service import retrieve, RetrievalResult, RetrievedChunk
from backend.services.llm_service import generate_answer
from backend.services.ingestion_service import _neo4j_note_id

logger = logging.getLogger(__name__)


@dataclass
class RAGAnswer:
    answer: str
    sources: list[dict]           # [{title, filename, score, note_id, chunk_id}]
    relationships: list[dict]     # [{source, relationship, target}]
    retrieved_chunks: list[dict]  # [{chunk_id, note_id, text, score, filename}]
    concepts: list[str]           # concept names found
    context_used: str
    chunks_used: int = 0
    user_id: str = ""
    error: str | None = None      # populated on LLM failure


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(result: RetrievalResult) -> str:
    """
    Build the structured prompt context from retrieved chunks and graph data.
    Contains ONLY the authenticated user's data.
    """
    sections: list[str] = []

    if result.chunks:
        doc_lines = ["RETRIEVED DOCUMENTS\n"]
        for chunk in result.chunks:
            source_label = chunk.note_filename or chunk.note_id or "unknown"
            score_label = f" (score: {chunk.score:.3f})" if chunk.score else ""
            doc_lines.append(f"[Source: {source_label}]{score_label}")
            doc_lines.append(chunk.text.strip())
            doc_lines.append("")
        sections.append("\n".join(doc_lines))

    if result.relationships:
        rel_lines = ["GRAPH RELATIONSHIPS\n"]
        seen: set[tuple] = set()
        for rel in result.relationships:
            key = (rel.get("source", ""), rel.get("relationship", ""), rel.get("target", ""))
            if key not in seen and all(key):
                seen.add(key)
                rel_lines.append(f"{key[0]} --[{key[1]}]--> {key[2]}")
        if len(rel_lines) > 1:
            sections.append("\n".join(rel_lines))

    return "\n\n".join(sections) if sections else "No relevant context found in your knowledge base."


def _deduplicate_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    """Return unique source notes, best score wins per note."""
    seen: dict[str, dict] = {}
    for chunk in chunks:
        key = chunk.note_id
        if key not in seen or chunk.score > seen[key]["score"]:
            seen[key] = {
                "title": chunk.note_title or chunk.note_id,
                "filename": chunk.note_filename or "",
                "score": chunk.score,
                "note_id": chunk.note_id,
                "chunk_id": chunk.chunk_id,
            }
    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)


def _build_retrieved_chunks(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "chunk_id": c.chunk_id,
            "note_id": c.note_id,
            "note_title": c.note_title,
            "note_filename": c.note_filename,
            "text": c.text,
            "score": c.score,
        }
        for c in chunks
    ]


# ── Public interface ──────────────────────────────────────────────────────────

def ask(
    question: str,
    user_id: str,
    top_k: int | None = None,
    graph_hops: int | None = None,
    note_id_filter: str | None = None,
) -> RAGAnswer:
    """
    USER-SCOPED GraphRAG pipeline.

    user_id is REQUIRED. All retrieval and generation is scoped to this user.
    No other user's data can appear in the answer, sources, or context.

    Args:
        question:       User's question.
        user_id:        Authenticated user UUID (from JWT, NEVER from client).
        top_k:          Override default chunk count.
        graph_hops:     Override traversal depth.
        note_id_filter: MySQL note UUID — restrict retrieval to one note.
    """
    logger.info("RAG query user=%s question=%s", user_id, question[:80])

    # Convert MySQL note ID → Neo4j note ID if filter provided
    neo4j_filter: str | None = None
    if note_id_filter:
        neo4j_filter = _neo4j_note_id(user_id, note_id_filter)

    # Step 1: Retrieve (user-scoped, optionally note-scoped)
    retrieval = retrieve(
        question,
        user_id=user_id,
        top_k=top_k,
        graph_hops=graph_hops,
        note_id_filter=neo4j_filter,
    )

    if not retrieval.chunks:
        logger.info("No chunks found for user=%s", user_id)
        return RAGAnswer(
            answer=(
                "I couldn't find enough information in your knowledge base to answer "
                "that confidently. Try uploading more notes or rephrasing your question."
            ),
            sources=[],
            relationships=[],
            retrieved_chunks=[],
            concepts=[],
            context_used="",
            chunks_used=0,
            user_id=user_id,
        )

    # Step 2: Build context (user data only)
    context = _build_context(retrieval)
    logger.debug("Context built: %d chars for user=%s", len(context), user_id)

    # Step 3: Generate answer with Groq LLM
    error_msg: str | None = None
    try:
        answer_text = generate_answer(question, context)
    except Exception as e:
        logger.error("LLM generation failed for user=%s: %s", user_id, e)
        answer_text = (
            "I retrieved relevant information from your knowledge base, "
            "but answer generation failed. Please try again."
        )
        error_msg = str(e)

    # Step 4: Package result — deduplicate, clean, return
    sources = _deduplicate_sources(retrieval.chunks)
    retrieved_chunks = _build_retrieved_chunks(retrieval.chunks)

    rels = [
        r for r in retrieval.relationships
        if r.get("source") and r.get("relationship") and r.get("target")
    ]
    seen_rels: set[tuple] = set()
    unique_rels: list[dict] = []
    for r in rels:
        k = (r["source"], r["relationship"], r["target"])
        if k not in seen_rels:
            seen_rels.add(k)
            unique_rels.append(r)

    return RAGAnswer(
        answer=answer_text,
        sources=sources,
        relationships=unique_rels,
        retrieved_chunks=retrieved_chunks,
        concepts=retrieval.concept_names,
        context_used=context,
        chunks_used=len(retrieval.chunks),
        user_id=user_id,
        error=error_msg,
    )
