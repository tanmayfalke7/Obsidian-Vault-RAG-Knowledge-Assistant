"""
Retrieval service — vector search + graph traversal.

Pipeline:
  question
    → embed (RETRIEVAL_QUERY task type)
    → Neo4j vector similarity search (top-K chunks)
    → For each chunk: traverse graph to find connected concepts
    → Return structured results
"""
import logging
from dataclasses import dataclass, field

from backend.db.neo4j_client import run_query
from backend.services.embedding_service import embed_query
from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    note_id: str
    text: str
    score: float
    note_title: str = ""
    note_filename: str = ""


@dataclass
class RetrievalResult:
    question: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)  # {source, rel, target}
    concept_names: list[str] = field(default_factory=list)


def vector_search(
    query_embedding: list[float],
    top_k: int,
    index_name: str,
    database: str,
) -> list[dict]:
    """
    Run Neo4j vector similarity search.
    Returns top-K chunks with their scores and source note info.
    """
    cypher = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
    YIELD node AS chunk, score
    MATCH (n:Note)-[:HAS_CHUNK]->(chunk)
    RETURN
      chunk.id          AS chunk_id,
      chunk.text        AS text,
      chunk.note_id     AS note_id,
      n.title           AS note_title,
      n.filename        AS note_filename,
      score
    ORDER BY score DESC
    """
    return run_query(
        cypher,
        {
            "index_name": index_name,
            "top_k": top_k,
            "embedding": query_embedding,
        },
        database=database,
    )


def expand_graph_from_chunks(
    chunk_ids: list[str],
    hops: int,
    database: str,
) -> list[dict]:
    """
    Traverse graph relationships from the matched chunks.

    For each chunk, follow:
    (chunk)-[:MENTIONS]->(concept)-[rel*1..hops]-(related_concept)

    Returns unique concept-relationship-concept triples.
    """
    if not chunk_ids:
        return []

    # Build the variable-length path pattern
    hop_pattern = f"[rel*1..{hops}]"

    cypher = f"""
    UNWIND $chunk_ids AS cid
    MATCH (chunk:Chunk {{id: cid}})-[:MENTIONS]->(concept:Concept)
    MATCH (concept)-{hop_pattern}-(related:Concept)
    WHERE concept <> related
    WITH concept, related,
         [(concept)-[r]->(related) | {{
           source: concept.name,
           relationship: type(r),
           target: related.name
         }}] AS direct_rels
    UNWIND direct_rels AS rel_triple
    RETURN DISTINCT
      rel_triple.source      AS source,
      rel_triple.relationship AS relationship,
      rel_triple.target      AS target
    LIMIT 30
    """
    return run_query(
        cypher,
        {"chunk_ids": chunk_ids},
        database=database,
    )


def get_related_concepts_for_chunks(
    chunk_ids: list[str],
    database: str,
) -> list[str]:
    """Return concept names directly mentioned by the given chunks."""
    if not chunk_ids:
        return []
    cypher = """
    UNWIND $chunk_ids AS cid
    MATCH (c:Chunk {id: cid})-[:MENTIONS]->(concept:Concept)
    RETURN DISTINCT concept.name AS name
    """
    results = run_query(cypher, {"chunk_ids": chunk_ids}, database=database)
    return [r["name"] for r in results if r.get("name")]


def retrieve(
    question: str,
    top_k: int = None,
    graph_hops: int = None,
) -> RetrievalResult:
    """
    Full GraphRAG retrieval:

    1. Embed question
    2. Vector search → top-K chunks
    3. Graph traversal from matched chunks
    4. Return structured result
    """
    k = top_k or settings.top_k
    hops = graph_hops or settings.graph_hops
    db = settings.neo4j_database
    index = settings.vector_index_name

    result = RetrievalResult(question=question)

    # Step 1: Embed query
    try:
        query_embedding = embed_query(question)
    except Exception as e:
        logger.error("Failed to embed query: %s", e)
        return result

    # Step 2: Vector search
    try:
        raw_results = vector_search(query_embedding, k, index, db)
    except Exception as e:
        logger.error("Vector search failed: %s", e)
        return result

    if not raw_results:
        logger.warning("Vector search returned no results for: %s", question)
        return result

    for row in raw_results:
        result.chunks.append(
            RetrievedChunk(
                chunk_id=row.get("chunk_id", ""),
                note_id=row.get("note_id", ""),
                text=row.get("text", ""),
                score=float(row.get("score", 0.0)),
                note_title=row.get("note_title", ""),
                note_filename=row.get("note_filename", ""),
            )
        )

    chunk_ids = [c.chunk_id for c in result.chunks]
    logger.info("Vector search: %d chunks retrieved.", len(chunk_ids))

    # Step 3: Get directly mentioned concepts
    result.concept_names = get_related_concepts_for_chunks(chunk_ids, db)
    logger.info("Direct concepts: %s", result.concept_names)

    # Step 4: Graph expansion
    try:
        graph_rows = expand_graph_from_chunks(chunk_ids, hops, db)
        result.relationships = graph_rows
        logger.info("Graph traversal: %d relationships found.", len(graph_rows))
    except Exception as e:
        logger.warning("Graph traversal failed (non-fatal): %s", e)

    return result
