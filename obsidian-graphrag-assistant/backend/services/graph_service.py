"""
Graph service — safe, predefined Cypher operations.

All Neo4j interactions outside of ingestion go through here.
No arbitrary Cypher is exposed to the public API.
"""
import logging
from typing import Optional

from backend.db.neo4j_client import run_query, get_session
from backend.core.config import settings

logger = logging.getLogger(__name__)

PROJECT = settings.project_tag


# ── Schema / Constraints ──────────────────────────────────────────────────────

def create_constraints_and_indexes() -> None:
    """Create uniqueness constraints and indexes. Safe to run repeatedly."""
    statements = [
        # Uniqueness constraints
        """
        CREATE CONSTRAINT note_id_unique IF NOT EXISTS
        FOR (n:Note) REQUIRE n.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
        FOR (c:Chunk) REQUIRE c.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT concept_id_unique IF NOT EXISTS
        FOR (c:Concept) REQUIRE c.id IS UNIQUE
        """,
        # Lookup indexes
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
    logger.info("Constraints and indexes ensured.")


def create_vector_index(
    index_name: str,
    dimensions: int,
    similarity: str = "cosine",
) -> None:
    """Create the Neo4j vector index on Chunk.embedding. Idempotent."""
    cypher = f"""
    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
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


# ── Node / Relationship creation ──────────────────────────────────────────────

def upsert_note(
    note_id: str,
    title: str,
    filename: str,
    filepath: str,
    content: str,
) -> None:
    """Create or update a Note node (GQL-compatible, no ON CREATE SET)."""
    # Check existence first, then merge + set
    cypher = """
    MERGE (n:Note {id: $id})
    SET n.title = $title,
        n.filename = $filename,
        n.filepath = $filepath,
        n.content = $content,
        n.project = $project,
        n.updated_at = datetime(),
        n.created_at = CASE WHEN n.created_at IS NULL THEN datetime() ELSE n.created_at END
    """
    run_query(
        cypher,
        {"id": note_id, "title": title, "filename": filename,
         "filepath": filepath, "content": content, "project": PROJECT},
        database=settings.neo4j_database,
    )


def upsert_chunk(
    chunk_id: str,
    note_id: str,
    text: str,
    chunk_index: int,
    embedding: Optional[list[float]] = None,
) -> None:
    """Create or update a Chunk node and link it to its Note."""
    cypher = """
    MERGE (c:Chunk {id: $chunk_id})
    SET c.text = $text,
        c.chunk_index = $chunk_index,
        c.note_id = $note_id,
        c.project = $project
    WITH c
    MATCH (n:Note {id: $note_id})
    MERGE (n)-[:HAS_CHUNK]->(c)
    """
    params: dict = {
        "chunk_id": chunk_id, "note_id": note_id,
        "text": text, "chunk_index": chunk_index, "project": PROJECT,
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


def upsert_concept(concept_id: str, name: str, concept_type: str = "concept") -> None:
    """Create or update a Concept node."""
    cypher = """
    MERGE (c:Concept {id: $id})
    SET c.name = $name,
        c.type = $type,
        c.project = $project
    """
    run_query(
        cypher,
        {"id": concept_id, "name": name, "type": concept_type, "project": PROJECT},
        database=settings.neo4j_database,
    )


def link_chunk_to_concept(chunk_id: str, concept_id: str) -> None:
    """Create MENTIONS relationship between Chunk and Concept."""
    cypher = """
    MATCH (c:Chunk {id: $chunk_id})
    MATCH (concept:Concept {id: $concept_id})
    MERGE (c)-[:MENTIONS]->(concept)
    """
    run_query(
        cypher,
        {"chunk_id": chunk_id, "concept_id": concept_id},
        database=settings.neo4j_database,
    )


def link_note_to_note(source_note_id: str, target_note_id: str) -> None:
    """Create LINKS_TO relationship between two Notes."""
    cypher = """
    MATCH (a:Note {id: $source_id})
    MATCH (b:Note {id: $target_id})
    MERGE (a)-[:LINKS_TO]->(b)
    """
    run_query(
        cypher,
        {"source_id": source_note_id, "target_id": target_note_id},
        database=settings.neo4j_database,
    )


def create_concept_relationship(
    source_id: str, rel_type: str, target_id: str
) -> None:
    """Create a named relationship between two Concept nodes."""
    # Validate rel_type to prevent injection — only allow known types
    allowed = {
        "RELATED_TO", "USES", "DEPENDS_ON", "ENABLES", "IMPLEMENTS",
        "BUILT_WITH", "EXTENDS", "STORES", "PROVIDES", "CONTAINS",
        "HAS_CONSTRAINT", "PREREQUISITE_OF", "SENT_TO", "SUPPORTS",
    }
    if rel_type not in allowed:
        logger.warning("Skipping unknown relationship type: %s", rel_type)
        return
    cypher = f"""
    MATCH (a:Concept {{id: $source}})
    MATCH (b:Concept {{id: $target}})
    MERGE (a)-[:{rel_type}]->(b)
    """
    run_query(
        cypher,
        {"source": source_id, "target": target_id},
        database=settings.neo4j_database,
    )


# ── Read queries ──────────────────────────────────────────────────────────────

def get_concept_neighbours(concept_name: str) -> list[dict]:
    """Return all 1-hop neighbours of a named concept."""
    cypher = """
    MATCH (c:Concept)
    WHERE toLower(c.name) = toLower($name)
    OPTIONAL MATCH (c)-[r_out]->(neighbour_out:Concept)
    OPTIONAL MATCH (c)<-[r_in]-(neighbour_in:Concept)
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
    results = run_query(
        cypher,
        {"name": concept_name},
        database=settings.neo4j_database,
    )
    return results


def get_graph_stats() -> dict:
    """Return counts for Notes, Chunks, Concepts, and Relationships."""
    cypher = """
    MATCH (n:Note {project: $project}) WITH count(n) AS notes
    MATCH (c:Chunk {project: $project}) WITH notes, count(c) AS chunks
    MATCH (concept:Concept {project: $project}) WITH notes, chunks, count(concept) AS concepts
    MATCH ()-[r]->() WITH notes, chunks, concepts, count(r) AS rels
    RETURN notes, chunks, concepts, rels
    """
    results = run_query(cypher, {"project": PROJECT}, database=settings.neo4j_database)
    if results:
        return results[0]
    return {"notes": 0, "chunks": 0, "concepts": 0, "rels": 0}


def get_all_notes() -> list[dict]:
    """Return basic info about all notes in the project."""
    cypher = """
    MATCH (n:Note {project: $project})
    OPTIONAL MATCH (n)-[:HAS_CHUNK]->(c:Chunk)
    RETURN n.id AS id, n.title AS title, n.filename AS filename,
           count(c) AS chunk_count
    ORDER BY n.filename
    """
    return run_query(cypher, {"project": PROJECT}, database=settings.neo4j_database)


def delete_project_data() -> dict:
    """
    Delete ALL nodes belonging to this project only.
    Returns counts of what was deleted.
    """
    # Get counts first
    stats = get_graph_stats()

    cypher = """
    MATCH (n {project: $project})
    DETACH DELETE n
    """
    run_query(cypher, {"project": PROJECT}, database=settings.neo4j_database)
    logger.warning(
        "Deleted project data: %s notes, %s chunks, %s concepts",
        stats.get("notes", 0),
        stats.get("chunks", 0),
        stats.get("concepts", 0),
    )
    return stats


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
