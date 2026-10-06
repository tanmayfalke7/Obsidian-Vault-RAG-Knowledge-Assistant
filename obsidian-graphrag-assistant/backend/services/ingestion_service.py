"""
Ingestion service — user-scoped Markdown ingestion into Neo4j.

Every node and relationship created here carries the user_id of the
authenticated user. No cross-tenant data is ever created or traversed.

ID scheme (deterministic, user-scoped):
  note_id:    {user_id}:{mysql_note_id}
  chunk_id:   {user_id}:{mysql_note_id}:chunk:{index}
  concept_id: {user_id}:concept:{normalized_name}

Public interface:
  ingest_note(note_id, user_id, content, title, filename)
    → Ingest a single user's Markdown note content
  run_ingestion(vault_path, user_id, reset)
    → Ingest the sample vault for a specific user
"""
import logging
import re
from pathlib import Path
from dataclasses import dataclass

import frontmatter

from backend.utils.markdown_parser import (
    parse_note, chunk_note, ParsedNote,
    _WIKI_LINK_RE, _H1_RE, _HEADING_RE,
)
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


# ── Concept relationship map (sample vault ontology) ────────────────────────
CONCEPT_RELATIONSHIPS: list[tuple[str, str, str]] = [
    ("AI", "RELATED_TO", "LLM"),
    ("LLM", "USES", "Prompt Engineering"),
    ("LLM", "HAS_CONSTRAINT", "Context Window"),
    ("RAG", "USES", "LLM"),
    ("RAG", "USES", "Embeddings"),
    ("RAG", "USES", "Retrieval"),
    ("RAG", "USES", "Generation"),
    ("RAG", "USES", "Vector Search"),
    ("RAG", "USES", "Chunking"),
    ("RAG", "RELATED_TO", "Semantic Search"),
    ("Embeddings", "ENABLES", "Semantic Search"),
    ("Embeddings", "ENABLES", "Vector Search"),
    ("Vector Search", "USES", "Embeddings"),
    ("Vector Search", "USES", "Vector Database"),
    ("Vector Database", "STORES", "Embeddings"),
    ("GraphRAG", "EXTENDS", "RAG"),
    ("GraphRAG", "USES", "Knowledge Graph"),
    ("GraphRAG", "USES", "Vector Search"),
    ("GraphRAG", "USES", "Neo4j"),
    ("GraphRAG", "USES", "Embeddings"),
    ("Knowledge Graph", "CONTAINS", "Concept"),
    ("Neo4j", "IMPLEMENTS", "Knowledge Graph"),
    ("Neo4j", "PROVIDES", "Vector Search"),
    ("FastAPI", "BUILT_WITH", "Python"),
    ("Streamlit", "BUILT_WITH", "Python"),
    ("JARVIS", "BUILT_WITH", "Python"),
    ("JARVIS", "USES", "LLM"),
    ("JARVIS", "USES", "MCP"),
    ("Chunking", "SUPPORTS", "Retrieval"),
    ("Retrieval", "PROVIDES", "Context"),
    ("Context Window", "RELATED_TO", "RAG"),
    ("Python", "PREREQUISITE_OF", "LLM"),
    ("LLM", "PREREQUISITE_OF", "Embeddings"),
    ("Embeddings", "PREREQUISITE_OF", "Vector Search"),
    ("Vector Search", "PREREQUISITE_OF", "RAG"),
    ("RAG", "PREREQUISITE_OF", "Knowledge Graph"),
    ("Knowledge Graph", "PREREQUISITE_OF", "GraphRAG"),
    ("GraphRAG", "PREREQUISITE_OF", "Neo4j"),
]


# ── User-scoped ID derivation ─────────────────────────────────────────────────

def _neo4j_note_id(user_id: str, mysql_note_id: str) -> str:
    """Stable Neo4j note ID: {user_id}:{note_id}"""
    return f"{user_id}:{mysql_note_id}"


def _neo4j_chunk_id(user_id: str, note_id: str, index: int) -> str:
    """Stable Neo4j chunk ID: {user_id}:{note_id}:chunk:{index}"""
    return f"{user_id}:{note_id}:chunk:{index}"


def _neo4j_concept_id(user_id: str, concept_name: str) -> str:
    """Stable Neo4j concept ID: {user_id}:concept:{normalized_name}"""
    slug = re.sub(r"[^a-z0-9]+", "-", concept_name.lower()).strip("-")
    return f"{user_id}:concept:{slug}"


def _slug_from_filename(filename: str) -> str:
    """Derive a slug from a filename stem (for vault-based note IDs)."""
    return re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")


# ── Markdown parsing from content string ────────────────────────────────────

def _parse_content(raw: str, filename: str) -> ParsedNote:
    """Parse Markdown content string into ParsedNote (no file I/O)."""
    try:
        post = frontmatter.loads(raw)
        meta: dict = dict(post.metadata)
        body: str = post.content
    except Exception:
        meta = {}
        body = raw

    title: str = str(meta.get("title", ""))
    if not title:
        h1_match = _H1_RE.search(body)
        title = h1_match.group(1).strip() if h1_match else Path(filename).stem

    headings = [m.group(2).strip() for m in _HEADING_RE.finditer(body)]

    raw_links = _WIKI_LINK_RE.findall(body)
    wiki_links = list(dict.fromkeys(
        link.strip().replace("_", " ") for link in raw_links
    ))

    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    tags = [str(t) for t in raw_tags]

    return ParsedNote(
        filename=filename,
        filepath="",
        title=title,
        content=raw,
        body=body,
        headings=headings,
        wiki_links=wiki_links,
        tags=tags,
        frontmatter_meta=meta,
    )


# ── Per-user concept management ──────────────────────────────────────────────

def ensure_user_concepts(
    user_id: str,
    concept_names: set[str],
    stats: IngestionStats,
) -> dict[str, str]:
    """Create per-user Concept nodes. Returns name→id map."""
    name_to_id: dict[str, str] = {}
    for name in sorted(concept_names):
        cid = _neo4j_concept_id(user_id, name)
        graph_service.upsert_concept(cid, user_id, name)
        name_to_id[name] = cid
        stats.concepts_created += 1
    logger.info("Ensured %d concepts for user %s", len(name_to_id), user_id)
    return name_to_id


def create_user_concept_relationships(
    user_id: str,
    concept_name_to_id: dict[str, str],
    stats: IngestionStats,
) -> None:
    """Create concept-to-concept relationships from the ontology map, scoped to user_id."""
    for src_name, rel_type, tgt_name in CONCEPT_RELATIONSHIPS:
        src_id = concept_name_to_id.get(src_name)
        tgt_id = concept_name_to_id.get(tgt_name)
        if not src_id or not tgt_id:
            continue
        graph_service.create_concept_relationship(src_id, rel_type, tgt_id, user_id)
        stats.relationships_created += 1


# ── Stale chunk cleanup ──────────────────────────────────────────────────────

def delete_stale_chunks(note_id: str, user_id: str) -> None:
    """Delete old chunks for a note before re-indexing. User-scoped."""
    cypher = """
    MATCH (c:Chunk {note_id: $note_id, user_id: $user_id})
    DETACH DELETE c
    """
    from backend.db.neo4j_client import run_query
    run_query(
        cypher,
        {"note_id": note_id, "user_id": user_id},
        database=settings.neo4j_database,
    )
    logger.debug("Deleted stale chunks for note %s (user %s)", note_id, user_id)


# ── Core: ingest a single note for a user ───────────────────────────────────

def ingest_note(
    note_id: str,
    user_id: str,
    content: str,
    title: str,
    filename: str,
    stats: IngestionStats | None = None,
) -> IngestionStats:
    """
    Ingest a single user's Markdown note into Neo4j.

    Args:
        note_id:   MySQL note UUID (stable cross-store identifier)
        user_id:   Authenticated user's UUID
        content:   Raw Markdown content
        title:     Note title
        filename:  Original filename (e.g. "my_note.md")
        stats:     Optional shared stats object

    Returns IngestionStats.
    """
    if stats is None:
        stats = IngestionStats()

    # User-scoped Neo4j IDs
    neo4j_note_id = _neo4j_note_id(user_id, note_id)

    # Ensure User node exists in Neo4j
    graph_service.upsert_user_node(user_id, name="")

    # Delete stale chunks from previous ingestion (re-index safety)
    delete_stale_chunks(neo4j_note_id, user_id)

    # Upsert Note node
    graph_service.upsert_note(
        note_id=neo4j_note_id,
        user_id=user_id,
        title=title,
        filename=filename,
        filepath="",
        content=content,
    )
    stats.notes_processed += 1

    # Parse markdown content
    parsed = _parse_content(content, filename)

    # Chunk the note
    chunks = chunk_note(parsed, max_chars=800, overlap=100)
    if not chunks:
        chunks = [parsed.body[:1500]] if parsed.body.strip() else []

    # Create Chunk nodes
    chunk_texts = []
    chunk_ids = []
    for i, chunk_text in enumerate(chunks):
        cid = _neo4j_chunk_id(user_id, note_id, i)
        graph_service.upsert_chunk(
            chunk_id=cid,
            user_id=user_id,
            note_id=neo4j_note_id,
            text=chunk_text,
            chunk_index=i,
        )
        chunk_ids.append(cid)
        chunk_texts.append(chunk_text)
        stats.chunks_created += 1

    # Generate embeddings
    if chunk_texts:
        try:
            embeddings = embedding_service.embed_texts(chunk_texts)
            for cid, emb in zip(chunk_ids, embeddings):
                if emb:
                    graph_service.set_chunk_embedding(cid, emb)
                    stats.embeddings_generated += 1
        except Exception as e:
            msg = f"Embedding failed for note {filename}: {e}"
            logger.error(msg)
            stats.errors.append(msg)

    # Extract concepts from wiki-links and create per-user Concept nodes
    wiki_concept_names = set(parsed.wiki_links)
    # Also add concepts from the hardcoded ontology that appear in wiki-links
    ontology_names = set()
    for src, _, tgt in CONCEPT_RELATIONSHIPS:
        if src in wiki_concept_names:
            ontology_names.add(src)
        if tgt in wiki_concept_names:
            ontology_names.add(tgt)

    all_concept_names = wiki_concept_names | ontology_names
    if all_concept_names:
        concept_name_to_id = ensure_user_concepts(user_id, all_concept_names, stats)

        # Link chunks → concepts via MENTIONS
        for link in parsed.wiki_links:
            concept_id = concept_name_to_id.get(link)
            if concept_id:
                for cid in chunk_ids:
                    graph_service.link_chunk_to_concept(cid, concept_id, user_id)
                    stats.relationships_created += 1

        # Create concept-to-concept relationships from the ontology
        create_user_concept_relationships(user_id, concept_name_to_id, stats)

    logger.info(
        "Ingested note %s for user %s: %d chunks, %d embeddings",
        filename, user_id, len(chunks), stats.embeddings_generated,
    )
    return stats


# ── Vault ingestion (sample vault, user-scoped) ──────────────────────────────

def run_ingestion(
    vault_path: Path,
    user_id: str = "system",
    reset: bool = False,
) -> IngestionStats:
    """
    Ingest the sample vault directory for a specific user.
    Each .md file becomes a note with a deterministic note_id derived from the filename.

    Args:
        vault_path: Path to the vault directory
        user_id:    The user to ingest for (default "system" for legacy compatibility)
        reset:      If True, delete this user's existing Neo4j data first
    """
    stats = IngestionStats()

    if reset:
        logger.warning("Resetting Neo4j data for user %s", user_id)
        graph_service.delete_user_neo4j_data(user_id)

    # Ensure schema
    graph_service.create_constraints_and_indexes()
    graph_service.create_vector_index(
        index_name=settings.vector_index_name,
        dimensions=settings.embedding_dimensions,
    )

    # Ensure User node
    graph_service.upsert_user_node(user_id, name="system")

    # Parse vault
    from backend.utils.markdown_parser import parse_vault
    notes = parse_vault(vault_path)
    if not notes:
        logger.error("No notes found in vault: %s", vault_path)
        stats.errors.append(f"No notes found in vault: {vault_path}")
        return stats

    logger.info("Starting vault ingestion of %d notes for user %s...", len(notes), user_id)

    # Ingest each note
    for note in notes:
        try:
            # Use a deterministic note_id derived from filename for the sample vault
            mysql_note_id = _slug_from_filename(note.filename)
            ingest_note(
                note_id=mysql_note_id,
                user_id=user_id,
                content=note.content,
                title=note.title,
                filename=note.filename,
                stats=stats,
            )
        except Exception as e:
            msg = f"Failed to ingest {note.filename}: {e}"
            logger.error(msg)
            stats.errors.append(msg)

    # Create note-to-note links based on wiki-links
    _create_note_to_note_links(notes, user_id, stats)

    logger.info(
        "Ingestion complete for user %s: Notes=%d Chunks=%d Concepts=%d Rels=%d Embeddings=%d Errors=%d",
        user_id,
        stats.notes_processed,
        stats.chunks_created,
        stats.concepts_created,
        stats.relationships_created,
        stats.embeddings_generated,
        len(stats.errors),
    )
    return stats


def _create_note_to_note_links(
    notes: list[ParsedNote],
    user_id: str,
    stats: IngestionStats,
) -> None:
    """Create LINKS_TO edges between notes based on wiki-link targets."""
    stem_map: dict[str, str] = {}
    for note in notes:
        stem = Path(note.filename).stem
        clean_stem = re.sub(r"^\d+_?", "", stem).replace("_", " ")
        slug = _slug_from_filename(note.filename)
        stem_map[clean_stem.lower()] = _neo4j_note_id(user_id, slug)

    for note in notes:
        source_slug = _slug_from_filename(note.filename)
        source_id = _neo4j_note_id(user_id, source_slug)
        for link in note.wiki_links:
            target_key = link.lower().replace("_", " ")
            target_id = stem_map.get(target_key)
            if target_id and target_id != source_id:
                graph_service.link_note_to_note(source_id, target_id, user_id)
                stats.relationships_created += 1
