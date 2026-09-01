"""
RAG service — orchestrates retrieval → context building → LLM generation.

This is the top-level coordinator. It calls retrieval_service to gather
chunks and graph context, formats them into a structured prompt context,
then calls llm_service to generate the final grounded answer.
"""
import logging
from dataclasses import dataclass, field

from backend.services.retrieval_service import retrieve, RetrievalResult
from backend.services.llm_service import generate_answer

logger = logging.getLogger(__name__)


@dataclass
class RAGAnswer:
    answer: str
    sources: list[dict]           # [{title, filename, score}]
    relationships: list[dict]     # [{source, relationship, target}]
    context_used: str             # the full context sent to LLM
    chunks_used: int = 0


def _build_context(result: RetrievalResult) -> str:
    """
    Construct the structured context string sent to the LLM.

    Format:
        RETRIEVED DOCUMENTS
        [Source: <filename>]
        <chunk text>
        ...

        GRAPH RELATIONSHIPS
        <source> --[RELATIONSHIP]--> <target>
        ...
    """
    sections = []

    # ── Retrieved document chunks ──────────────────────────────────────────
    if result.chunks:
        doc_lines = ["RETRIEVED DOCUMENTS\n"]
        seen_sources: set[str] = set()
        for chunk in result.chunks:
            source_label = chunk.note_filename or chunk.note_id or "unknown"
            score_label = f" (score: {chunk.score:.3f})" if chunk.score else ""
            doc_lines.append(f"[Source: {source_label}]{score_label}")
            doc_lines.append(chunk.text.strip())
            doc_lines.append("")
            seen_sources.add(source_label)
        sections.append("\n".join(doc_lines))

    # ── Graph relationships ────────────────────────────────────────────────
    if result.relationships:
        rel_lines = ["GRAPH RELATIONSHIPS\n"]
        seen_rels: set[tuple] = set()
        for rel in result.relationships:
            key = (rel.get("source", ""), rel.get("relationship", ""), rel.get("target", ""))
            if key in seen_rels:
                continue
            seen_rels.add(key)
            if all(key):
                rel_lines.append(
                    f"{key[0]} --[{key[1]}]--> {key[2]}"
                )
        if len(rel_lines) > 1:
            sections.append("\n".join(rel_lines))

    return "\n\n".join(sections) if sections else "No relevant context found."


def _deduplicate_sources(chunks) -> list[dict]:
    """Return unique source notes from chunks, sorted by best score."""
    seen: dict[str, dict] = {}
    for chunk in chunks:
        key = chunk.note_filename or chunk.note_id
        if key not in seen or chunk.score > seen[key]["score"]:
            seen[key] = {
                "title": chunk.note_title or chunk.note_id,
                "filename": chunk.note_filename or chunk.note_id,
                "score": chunk.score,
            }
    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)


def ask(
    question: str,
    top_k: int = None,
    graph_hops: int = None,
) -> RAGAnswer:
    """
    Full GraphRAG pipeline:

    1. Retrieve chunks + graph context
    2. Build structured context
    3. Generate LLM answer
    4. Return answer + sources + relationships
    """
    logger.info("RAG query: %s", question)

    # Step 1: Retrieve
    retrieval = retrieve(question, top_k=top_k, graph_hops=graph_hops)

    if not retrieval.chunks:
        no_context_answer = (
            "I couldn't find enough information in the knowledge base to answer that confidently. "
            "The vault may not have been ingested yet, or the question may be outside the scope "
            "of the stored knowledge."
        )
        return RAGAnswer(
            answer=no_context_answer,
            sources=[],
            relationships=[],
            context_used="",
            chunks_used=0,
        )

    # Step 2: Build context
    context = _build_context(retrieval)
    logger.debug("Built context (%d chars) for LLM.", len(context))

    # Step 3: Generate
    try:
        answer_text = generate_answer(question, context)
    except Exception as e:
        logger.error("LLM generation failed: %s", e)
        answer_text = (
            f"I retrieved relevant information from the knowledge base, but "
            f"answer generation failed: {e}. Please check the Groq API configuration."
        )

    # Step 4: Package result
    sources = _deduplicate_sources(retrieval.chunks)
    relationships = [
        r for r in retrieval.relationships
        if r.get("source") and r.get("relationship") and r.get("target")
    ]
    # Deduplicate relationships
    seen_rels: set[tuple] = set()
    unique_rels = []
    for r in relationships:
        key = (r["source"], r["relationship"], r["target"])
        if key not in seen_rels:
            seen_rels.add(key)
            unique_rels.append(r)

    return RAGAnswer(
        answer=answer_text,
        sources=sources,
        relationships=unique_rels,
        context_used=context,
        chunks_used=len(retrieval.chunks),
    )
