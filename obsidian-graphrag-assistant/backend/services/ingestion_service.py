"""
Ingestion service — orchestrates parsing, chunking, embedding, and graph building.

Pipeline:
  data/vault/*.md
      → parse_vault()
      → chunk_note()
      → embed_texts()
      → upsert Note / Chunk / Concept nodes
      → create relationships
"""
import logging
import re
from pathlib import Path
from dataclasses import dataclass

from backend.utils.markdown_parser import parse_vault, chunk_note, ParsedNote
from backend.services import embedding_service, graph_service
from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class IngestionStats:
    notes_processed: int = 0
    chunks_created: int = 0
    concepts_created: int = 0
    relationships_created: int = 0
    embeddings_generated: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ── Concept relationship map ───────────────────────────────────────────────────
# Declarative definition of concept-to-concept relationships for the sample vault.
# These mirror the spec's required relationships.
CONCEPT_RELATIONSHIPS: list[tuple[str, str, str]] = [
    # AI domain
    ("AI", "RELATED_TO", "LLM"),
    ("LLM", "USES", "Prompt Engineering"),
    ("LLM", "HAS_CONSTRAINT", "Context Window"),
    # RAG ecosystem
    ("RAG", "USES", "LLM"),
    ("RAG", "USES", "Embeddings"),
    ("RAG", "USES", "Retrieval"),
    ("RAG", "USES", "Generation"),
    ("RAG", "USES", "Vector Search"),
    ("RAG", "USES", "Chunking"),
    ("RAG", "RELATED_TO", "Semantic Search"),
    # Embeddings chain
    ("Embeddings", "ENABLES", "Semantic Search"),
    ("Embeddings", "ENABLES", "Vector Search"),
    # Vector search
    ("Vector Search", "USES", "Embeddings"),
    ("Vector Search", "USES", "Vector Database"),
    ("Vector Database", "STORES", "Embeddings"),
    # GraphRAG
    ("GraphRAG", "EXTENDS", "RAG"),
    ("GraphRAG", "USES", "Knowledge Graph"),
    ("GraphRAG", "USES", "Vector Search"),
    ("GraphRAG", "USES", "Neo4j"),
    ("GraphRAG", "USES", "Embeddings"),
    # Knowledge graph
    ("Knowledge Graph", "CONTAINS", "Concept"),
    ("Neo4j", "IMPLEMENTS", "Knowledge Graph"),
    ("Neo4j", "PROVIDES", "Vector Search"),
    # Framework
    ("FastAPI", "BUILT_WITH", "Python"),
    ("Streamlit", "BUILT_WITH", "Python"),
    # JARVIS
    ("JARVIS", "BUILT_WITH", "Python"),
    ("JARVIS", "USES", "LLM"),
    ("JARVIS", "USES", "MCP"),
    # Retrieval chain
    ("Chunking", "SUPPORTS", "Retrieval"),
    ("Retrieval", "PROVIDES", "Context"),
    ("Context Window", "RELATED_TO", "RAG"),
    # Learning path prerequisites
    ("Python", "PREREQUISITE_OF", "LLM"),
    ("LLM", "PREREQUISITE_OF", "Embeddings"),
    ("Embeddings", "PREREQUISITE_OF", "Vector Search"),
    ("Vector Search", "PREREQUISITE_OF", "RAG"),
    ("RAG", "PREREQUISITE_OF", "Knowledge Graph"),
    ("Knowledge Graph", "PREREQUISITE_OF", "GraphRAG"),
    ("GraphRAG", "PREREQUISITE_OF", "Neo4j"),
]


def _concept_id(name: str) -> str:
    """Derive a stable, lowercase slug ID from a concept name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _note_id(filename: str) -> str:
    """Derive a stable ID from a note filename."""
    return re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")


def _chunk_id(note_id: str, index: int) -> str:
    return f"{note_id}-chunk-{index}"


def ensure_all_concepts(stats: IngestionStats) -> dict[str, str]:
    """
    Ensure all known concepts exist in Neo4j.
    Returns a name → id mapping.
    """
    all_names: set[str] = set()
    for src, _, tgt in CONCEPT_RELATIONSHIPS:
        all_names.add(src)
        all_names.add(tgt)

    name_to_id: dict[str, str] = {}
    for name in sorted(all_names):
        cid = _concept_id(name)
        graph_service.upsert_concept(cid, name)
        name_to_id[name] = cid
        stats.concepts_created += 1

    logger.info("Ensured %d concepts in graph.", len(name_to_id))
    return name_to_id


def create_concept_relationships(
    concept_name_to_id: dict[str, str], stats: IngestionStats
) -> None:
    """Create all predefined concept-to-concept relationships."""
    for src_name, rel_type, tgt_name in CONCEPT_RELATIONSHIPS:
        src_id = concept_name_to_id.get(src_name)
        tgt_id = concept_name_to_id.get(tgt_name)
        if not src_id or not tgt_id:
            logger.warning("Missing concept for relationship: %s → %s", src_name, tgt_name)
            continue
        graph_service.create_concept_relationship(src_id, rel_type, tgt_id)
        stats.relationships_created += 1

    logger.info("Created %d concept relationships.", stats.relationships_created)


def ingest_note(
    note: ParsedNote,
    concept_name_to_id: dict[str, str],
    stats: IngestionStats,
) -> None:
    """Process a single note: upsert it, chunk it, link to concepts."""
    note_id = _note_id(note.filename)

    # Upsert Note node
    graph_service.upsert_note(
        note_id=note_id,
        title=note.title,
        filename=note.filename,
        filepath=note.filepath,
        content=note.content,
    )
    stats.notes_processed += 1

    # Chunk the note
    chunks = chunk_note(note, max_chars=800, overlap=100)
    if not chunks:
        chunks = [note.body[:1500]] if note.body.strip() else []

    chunk_texts = []
    chunk_ids = []
    for i, chunk_text in enumerate(chunks):
        cid = _chunk_id(note_id, i)
        graph_service.upsert_chunk(
            chunk_id=cid,
            note_id=note_id,
            text=chunk_text,
            chunk_index=i,
        )
        chunk_ids.append(cid)
        chunk_texts.append(chunk_text)
        stats.chunks_created += 1

    # Generate embeddings for all chunks in this note
    if chunk_texts:
        try:
            embeddings = embedding_service.embed_texts(chunk_texts)
            for cid, emb in zip(chunk_ids, embeddings):
                if emb:
                    graph_service.set_chunk_embedding(cid, emb)
                    stats.embeddings_generated += 1
        except Exception as e:
            msg = f"Embedding failed for note {note.filename}: {e}"
            logger.error(msg)
            stats.errors.append(msg)

    # Link chunks → concepts via MENTIONS (based on wiki-links in body)
    for link in note.wiki_links:
        concept_id = concept_name_to_id.get(link)
        if concept_id:
            for cid in chunk_ids:
                graph_service.link_chunk_to_concept(cid, concept_id)
                stats.relationships_created += 1


def ingest_note_to_note_links(
    notes: list[ParsedNote],
    stats: IngestionStats,
) -> None:
    """
    After all notes are ingested, create LINKS_TO edges between notes
    based on wiki-link targets that match a note stem.
    """
    # Build a map: normalised stem → note_id
    stem_map: dict[str, str] = {}
    for note in notes:
        stem = Path(note.filename).stem
        # Remove numeric prefix (e.g. "03_RAG" → "RAG", "03_RAG" → "03 RAG")
        clean_stem = re.sub(r"^\d+_?", "", stem).replace("_", " ")
        stem_map[clean_stem.lower()] = _note_id(note.filename)

    for note in notes:
        source_id = _note_id(note.filename)
        for link in note.wiki_links:
            target_key = link.lower().replace("_", " ")
            target_id = stem_map.get(target_key)
            if target_id and target_id != source_id:
                graph_service.link_note_to_note(source_id, target_id)
                stats.relationships_created += 1


def run_ingestion(vault_path: Path, reset: bool = False) -> IngestionStats:
    """
    Full ingestion pipeline.

    1. Optionally reset project data
    2. Ensure constraints / indexes / vector index
    3. Ensure concepts
    4. Parse vault
    5. Ingest each note (chunks + embeddings + links)
    6. Create concept-to-concept relationships
    7. Create note-to-note links

    Returns IngestionStats.
    """
    stats = IngestionStats()

    if reset:
        logger.warning("Resetting project data as requested.")
        graph_service.delete_project_data()

    # Ensure schema
    graph_service.create_constraints_and_indexes()
    graph_service.create_vector_index(
        index_name=settings.vector_index_name,
        dimensions=settings.embedding_dimensions,
    )

    # Ensure all concepts exist first
    concept_name_to_id = ensure_all_concepts(stats)

    # Parse vault
    notes = parse_vault(vault_path)
    if not notes:
        logger.error("No notes found in vault: %s", vault_path)
        stats.errors.append(f"No notes found in vault: {vault_path}")
        return stats

    logger.info("Starting ingestion of %d notes...", len(notes))

    # Ingest each note
    for note in notes:
        try:
            ingest_note(note, concept_name_to_id, stats)
            logger.info(
                "Ingested: %s (concepts=%d, errors_so_far=%d)",
                note.filename,
                len(note.wiki_links),
                len(stats.errors),
            )
        except Exception as e:
            msg = f"Failed to ingest {note.filename}: {e}"
            logger.error(msg)
            stats.errors.append(msg)

    # Concept-to-concept relationships
    create_concept_relationships(concept_name_to_id, stats)

    # Note-to-note links
    ingest_note_to_note_links(notes, stats)

    logger.info(
        "Ingestion complete. Notes=%d Chunks=%d Concepts=%d Rels=%d Embeddings=%d Errors=%d",
        stats.notes_processed,
        stats.chunks_created,
        stats.concepts_created,
        stats.relationships_created,
        stats.embeddings_generated,
        len(stats.errors),
    )
    return stats
