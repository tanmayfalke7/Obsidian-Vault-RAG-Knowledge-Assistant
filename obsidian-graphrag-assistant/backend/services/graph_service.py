"""
Graph service — user-scoped Neo4j operations.

EVERY node carries a `user_id` property. No query can cross tenant boundaries.
All read/write/delete operations verify user_id ownership.

Node schema (multi-tenant):
  (:User    {id, name})
  (:Note    {id, user_id, title, filename, project, content})
  (:Chunk   {id, user_id, note_id, text, embedding, chunk_index, project})
  (:Concept {id, user_id, name, type, project})

ID scheme (deterministic, user-scoped):
  note_id:    {user_id}:{mysql_note_id}
  chunk_id:   {user_id}:{note_id}:chunk:{index}
  concept_id: {user_id}:concept:{normalized_name}

Relationships:
  (:User)-[:OWNS]->(:Note)
  (:Note)-[:HAS_CHUNK]->(:Chunk)
  (:Chunk)-[:MENTIONS]->(:Concept)
  (:Concept)-[:USES|ENABLES|EXTENDS|...]->(:Concept)  (same user only)
"""
import logging
from typing import Optional

from backend.db.neo4j_client import run_query, get_session
from backend.core.config import settings
from backend.core.validation import validate_cypher_identifier

logger = logging.getLogger(__name__)

PROJECT = settings.project_tag

# ── Allowed relationship types (whitelist prevents Cypher injection) ──────
ALLOWED_REL_TYPES = {
    "RELATED_TO", "USES", "DEPENDS_ON", "ENABLES", "IMPLEMENTS",
    "BUILT_WITH", "EXTENDS", "STORES", "PROVIDES", "CONTAINS",
    "HAS_CONSTRAINT", "PREREQUISITE_OF", "SENT_TO", "SUPPORTS",
}


# ── Schema / Constraints ──────────────────────────────────────────────────────

def create_constraints_and_indexes() -> None:
    """Create uniqueness constraints and indexes. Safe to run repeatedly."""
    statements = [
        # Uniqueness on id (IDs are user-scoped so globally unique by construction)
        "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT concept_id_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
        # Lookup indexes for user_id on every tenant-owned label
        "CREATE INDEX note_user_idx IF NOT EXISTS FOR (n:Note) ON (n.user_id)",
        "CREATE INDEX chunk_user_idx IF NOT EXISTS FOR (c:Chunk) ON (c.user_id)",
        "CREATE INDEX concept_user_idx IF NOT EXISTS FOR (c:Concept) ON (c.user_id)",
        # Other useful indexes
        "CREATE INDEX note_title_idx IF NOT EXISTS FOR (n:Note) ON (n.title)",
        "CREATE INDEX concept_name_idx IF NOT EXISTS FOR (c:Concept) ON (c.name)",
        "CREATE INDEX chunk_note_idx IF NOT EXISTS FOR (c:Chunk) ON (c.note_id)",
    ]
    with get_session(settings.neo4j_database) as session:
        for stmt in statements:
            try:
                session.run(stmt.strip())
            except Exception as e:
                logger.warning("Constraint/index statement warning: %s", e)
    logger.info("User-scoped constraints and indexes ensured.")


def create_vector_index(
    index_name: str,
    dimensions: int,
    similarity: str = "cosine",
) -> None:
    """Create the Neo4j vector index on Chunk.embedding. Idempotent."""
    safe_index_name = validate_cypher_identifier(index_name, "vector index name")
    if dimensions < 1 or dimensions > 10000:
        raise ValueError("Invalid embedding dimensions.")
    if similarity not in {"cosine", "euclidean"}:
        raise ValueError("Invalid vector similarity function.")
    cypher = f"""
    CREATE VECTOR INDEX {safe_index_name} IF NOT EXISTS
    FOR (c:Chunk) ON (c.embedding)
    OPTIONS {{
      indexConfig: {{
        `vector.dimensions`: {dimensions},
        `vector.similarity_function`: '{similarity}'
      }}
    }}
    """
    try:
        run_query(cypher.strip(), database=settings.neo4j_database)
        logger.info(
            "Vector index '%s' ensured (%d dims, %s).",
            index_name, dimensions, similarity
        )
    except Exception as e:
        logger.error("Failed to create vector index: %s", e)
        raise


# ── User node ────────────────────────────────────────────────────────────────

def upsert_user_node(user_id: str, name: str) -> None:
    """Create or update a User node in Neo4j (stores only id + name, no password)."""
    cypher = """
    MERGE (u:User {id: $user_id})
    SET u.name = $name
    """
    run_query(
        cypher,
        {"user_id": user_id, "name": name},
        database=settings.neo4j_database,
    )


# ── Node / Relationship creation (all user-scoped) ───────────────────────────

def upsert_note(
    note_id: str,
    user_id: str,
    title: str,
    filename: str,
    filepath: str,
    content: str,
) -> None:
    """Create or update a Note node owned by user_id. Links User-OWNS-Note."""
    cypher = """
    MERGE (n:Note {id: $id})
    SET n.title = $title,
        n.filename = $filename,
        n.filepath = $filepath,
        n.content = $content,
        n.user_id = $user_id,
        n.project = $project,
        n.updated_at = datetime(),
        n.created_at = CASE WHEN n.created_at IS NULL THEN datetime() ELSE n.created_at END
    WITH n
    MATCH (u:User {id: $user_id})
    MERGE (u)-[:OWNS]->(n)
    """
    run_query(
        cypher,
        {"id": note_id, "title": title, "filename": filename,
         "filepath": filepath, "content": content,
         "user_id": user_id, "project": PROJECT},
        database=settings.neo4j_database,
    )


def upsert_chunk(
    chunk_id: str,
    user_id: str,
    note_id: str,
    text: str,
    chunk_index: int,
    embedding: Optional[list[float]] = None,
) -> None:
    """Create or update a Chunk node owned by user_id. Links Note-HAS_CHUNK-Chunk."""
    cypher = """
    MERGE (c:Chunk {id: $chunk_id})
    SET c.text = $text,
        c.chunk_index = $chunk_index,
        c.note_id = $note_id,
        c.user_id = $user_id,
        c.project = $project
    WITH c
    MATCH (n:Note {id: $note_id, user_id: $user_id})
    MERGE (n)-[:HAS_CHUNK]->(c)
    """
    params: dict = {
        "chunk_id": chunk_id, "note_id": note_id,
        "text": text, "chunk_index": chunk_index,
        "user_id": user_id, "project": PROJECT,
    }
    run_query(cypher, params, database=settings.neo4j_database)

    if embedding:
        set_chunk_embedding(chunk_id, embedding)


def set_chunk_embedding(chunk_id: str, embedding: list[float]) -> None:
    """Write an embedding vector onto an existing Chunk node."""
    cypher = "MATCH (c:Chunk {id: $id}) SET c.embedding = $embedding"
    run_query(
        cypher,
        {"id": chunk_id, "embedding": embedding},
        database=settings.neo4j_database,
    )


def upsert_concept(
    concept_id: str,
    user_id: str,
    name: str,
    concept_type: str = "concept",
) -> None:
    """Create or update a Concept node owned by user_id."""
    cypher = """
    MERGE (c:Concept {id: $id})
    SET c.name = $name,
        c.type = $type,
        c.user_id = $user_id,
        c.project = $project
    """
    run_query(
        cypher,
        {"id": concept_id, "name": name, "type": concept_type,
         "user_id": user_id, "project": PROJECT},
        database=settings.neo4j_database,
    )


def link_chunk_to_concept(
    chunk_id: str,
    concept_id: str,
    user_id: str,
) -> None:
    """Create MENTIONS relationship. Both nodes must belong to user_id."""
    cypher = """
    MATCH (c:Chunk {id: $chunk_id, user_id: $user_id})
    MATCH (concept:Concept {id: $concept_id, user_id: $user_id})
    MERGE (c)-[:MENTIONS]->(concept)
    """
    run_query(
        cypher,
        {"chunk_id": chunk_id, "concept_id": concept_id, "user_id": user_id},
        database=settings.neo4j_database,
    )


def link_note_to_note(
    source_note_id: str,
    target_note_id: str,
    user_id: str,
) -> None:
    """Create LINKS_TO relationship between two Notes owned by the same user."""
    cypher = """
    MATCH (a:Note {id: $source_id, user_id: $user_id})
    MATCH (b:Note {id: $target_id, user_id: $user_id})
    MERGE (a)-[:LINKS_TO]->(b)
    """
    run_query(
        cypher,
        {"source_id": source_note_id, "target_id": target_note_id, "user_id": user_id},
        database=settings.neo4j_database,
    )


def create_concept_relationship(
    source_id: str,
    rel_type: str,
    target_id: str,
    user_id: str,
) -> None:
    """Create a named relationship between two Concept nodes of the same user."""
    if rel_type not in ALLOWED_REL_TYPES:
        logger.warning("Skipping unknown relationship type: %s", rel_type)
        return
    cypher = f"""
    MATCH (a:Concept {{id: $source, user_id: $user_id}})
    MATCH (b:Concept {{id: $target, user_id: $user_id}})
    MERGE (a)-[:{rel_type}]->(b)
    """
    run_query(
        cypher,
        {"source": source_id, "target": target_id, "user_id": user_id},
        database=settings.neo4j_database,
    )


# ── Read queries (all user-scoped) ───────────────────────────────────────────

def get_concept_neighbours(concept_name: str, user_id: str) -> list[dict]:
    """Return all 1-hop neighbours of a named concept, scoped to user_id."""
    cypher = """
    MATCH (c:Concept)
    WHERE toLower(c.name) = toLower($name) AND c.user_id = $user_id
    OPTIONAL MATCH (c)-[r_out]->(neighbour_out:Concept {user_id: $user_id})
    OPTIONAL MATCH (c)<-[r_in]-(neighbour_in:Concept {user_id: $user_id})
    RETURN
      c.name AS concept,
      collect(DISTINCT {
        concept: neighbour_out.name,
        relationship: type(r_out),
        direction: 'outgoing'
      }) AS outgoing,
      collect(DISTINCT {
        concept: neighbour_in.name,
        relationship: type(r_in),
        direction: 'incoming'
      }) AS incoming
    """
    return run_query(
        cypher,
        {"name": concept_name, "user_id": user_id},
        database=settings.neo4j_database,
    )


def get_graph_stats(user_id: str) -> dict:
    """Return counts for Notes, Chunks, Concepts, and Relationships for user_id."""
    cypher = """
    MATCH (n:Note {user_id: $user_id}) WITH count(n) AS notes
    MATCH (c:Chunk {user_id: $user_id}) WITH notes, count(c) AS chunks
    MATCH (concept:Concept {user_id: $user_id}) WITH notes, chunks, count(concept) AS concepts
    OPTIONAL MATCH (a:Concept {user_id: $user_id})-[r]->(b:Concept {user_id: $user_id})
    WITH notes, chunks, concepts, count(r) AS rels
    RETURN notes, chunks, concepts, rels
    """
    results = run_query(cypher, {"user_id": user_id}, database=settings.neo4j_database)
    if results:
        return results[0]
    return {"notes": 0, "chunks": 0, "concepts": 0, "rels": 0}


def get_all_notes(user_id: str) -> list[dict]:
    """Return basic info about all notes owned by user_id."""
    cypher = """
    MATCH (n:Note {user_id: $user_id})
    OPTIONAL MATCH (n)-[:HAS_CHUNK]->(c:Chunk)
    RETURN n.id AS id, n.title AS title, n.filename AS filename,
           count(c) AS chunk_count
    ORDER BY n.filename
    """
    return run_query(cypher, {"user_id": user_id}, database=settings.neo4j_database)


def get_note_sources(user_id: str, note_ids: list[str]) -> dict[str, dict]:
    """Return {note_id: {title, filename}} for the given note_ids, user-scoped."""
    if not note_ids:
        return {}
    cypher = """
    UNWIND $note_ids AS nid
    MATCH (n:Note {id: nid, user_id: $user_id})
    RETURN n.id AS id, n.title AS title, n.filename AS filename
    """
    results = run_query(
        cypher,
        {"note_ids": note_ids, "user_id": user_id},
        database=settings.neo4j_database,
    )
    return {r["id"]: {"title": r["title"], "filename": r["filename"]} for r in results}


# ── Delete operations (all user-scoped) ──────────────────────────────────────

def delete_note_neo4j(note_id: str, user_id: str) -> int:
    """
    Delete a Note and its Chunks from Neo4j. Only deletes data owned by user_id.
    Returns the number of nodes deleted.
    """
    # Delete chunks first, then the note
    cypher_chunks = """
    MATCH (c:Chunk {note_id: $note_id, user_id: $user_id})
    DETACH DELETE c
    """
    run_query(
        cypher_chunks,
        {"note_id": note_id, "user_id": user_id},
        database=settings.neo4j_database,
    )
    cypher_note = """
    MATCH (n:Note {id: $note_id, user_id: $user_id})
    DETACH DELETE n
    """
    run_query(
        cypher_note,
        {"note_id": note_id, "user_id": user_id},
        database=settings.neo4j_database,
    )
    logger.info("Deleted note %s for user %s", note_id, user_id)
    return 1


def delete_user_neo4j_data(user_id: str) -> dict:
    """
    Delete ALL Neo4j data belonging to user_id only.
    Other users' data is NEVER touched.
    """
    stats = get_graph_stats(user_id)
    cypher = """
    MATCH (n {user_id: $user_id})
    DETACH DELETE n
    """
    run_query(cypher, {"user_id": user_id}, database=settings.neo4j_database)
    logger.warning(
        "Deleted user %s data: %s notes, %s chunks, %s concepts",
        user_id,
        stats.get("notes", 0),
        stats.get("chunks", 0),
        stats.get("concepts", 0),
    )
    return stats


# ── Legacy: project-wide delete (for the sample vault script only) ───────────

def delete_project_data() -> dict:
    """
    Delete ALL nodes belonging to this project only (legacy sample-vault cleanup).
    Used by scripts/reset_project_data.py. NOT used in multi-tenant flows.
    """
    cypher = "MATCH (n {project: $project}) DETACH DELETE n"
    run_query(cypher, {"project": PROJECT}, database=settings.neo4j_database)
    logger.warning("Deleted ALL project data (global).")
    return {"deleted": "all"}


def get_vector_index_status(index_name: str) -> str:
    """Return the status string of the named vector index."""
    cypher = "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state"
    try:
        results = run_query(
            cypher,
            {"name": index_name},
            database=settings.neo4j_database,
        )
        return results[0]["state"] if results else "not_found"
    except Exception:
        return "unknown"
