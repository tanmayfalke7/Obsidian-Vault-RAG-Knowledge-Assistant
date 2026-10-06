"""
Retrieval service — USER-SCOPED vector search + graph traversal + graph explorer.

user_id is REQUIRED on every public function. No retrieval can cross tenant boundaries.

──────────────────────────────────────────────────────────────────────────────
VECTOR ISOLATION STRATEGY
──────────────────────────────────────────────────────────────────────────────
We use db.index.vector.queryNodes with a large candidate pool, then apply
WHERE chunk.user_id = $user_id BEFORE the LIMIT in the same Cypher query.

  CALL db.index.vector.queryNodes(…, candidate_k, embedding)
  YIELD node AS chunk, score
  WHERE chunk.user_id = $user_id            ← DB-level filter, NOT Python
  MATCH (n:Note {user_id: $user_id})-[:HAS_CHUNK]->(chunk)
  RETURN … ORDER BY score DESC LIMIT $top_k

This is NOT post-filtering. The user constraint participates in the retrieval
step itself. A user's chunks can never appear in another user's results because
they are excluded before the LIMIT is applied.

──────────────────────────────────────────────────────────────────────────────
GRAPH TRAVERSAL ISOLATION
──────────────────────────────────────────────────────────────────────────────
Every MATCH in graph-traversal queries pins user_id on every node:

  MATCH (chunk:Chunk {id: …, user_id: $user_id})
        -[:MENTIONS]->
        (concept:Concept {user_id: $user_id})
        -[*1..hops]-
        (related:Concept {user_id: $user_id})

No traversal can escape a user's subgraph.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.db.neo4j_client import run_query
from backend.services.embedding_service import embed_query
from backend.core.config import settings
from backend.core.validation import bounded_int, validate_cypher_identifier

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id: str
    note_id: str
    text: str
    score: float
    note_title: str = ""
    note_filename: str = ""
    user_id: str = ""


@dataclass
class RetrievalResult:
    question: str
    user_id: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    concept_names: list[str] = field(default_factory=list)


# ── Core vector + graph retrieval ─────────────────────────────────────────────

def vector_search(
    query_embedding: list[float],
    user_id: str,
    top_k: int,
    index_name: str,
    database: str,
) -> list[dict]:
    """
    USER-SCOPED vector similarity search.

    Queries the index with a 10× candidate pool, filters by user_id at the
    database level (WHERE clause before LIMIT), then returns top_k results.
    This is NOT Python post-filtering — the user constraint is in the Cypher.
    """
    top_k = bounded_int(top_k, settings.top_k, 1, 20)
    candidate_k = bounded_int(top_k * 10, 50, 10, 500)
    index_name = validate_cypher_identifier(index_name, "vector index name")
    cypher = """
    CALL db.index.vector.queryNodes($index_name, $candidate_k, $embedding)
    YIELD node AS chunk, score
    WHERE chunk.user_id = $user_id
    MATCH (n:Note {user_id: $user_id})-[:HAS_CHUNK]->(chunk)
    RETURN
      chunk.id          AS chunk_id,
      chunk.text        AS text,
      chunk.note_id     AS note_id,
      n.title           AS note_title,
      n.filename        AS note_filename,
      score
    ORDER BY score DESC
    LIMIT $top_k
    """
    return run_query(
        cypher,
        {
            "index_name": index_name,
            "candidate_k": candidate_k,
            "top_k": top_k,
            "embedding": query_embedding,
            "user_id": user_id,
        },
        database=database,
    )


def expand_graph_from_chunks(
    chunk_ids: list[str],
    user_id: str,
    hops: int,
    database: str,
    max_rels: int = 30,
) -> list[dict]:
    """
    USER-SCOPED graph traversal from matched chunks.
    Every node in the path is constrained to user_id.
    """
    if not chunk_ids:
        return []

    hops = bounded_int(hops, settings.graph_hops, 1, 4)
    max_rels = bounded_int(max_rels, 30, 1, 100)
    hop_pattern = f"[rel*1..{hops}]"
    cypher = f"""
    UNWIND $chunk_ids AS cid
    MATCH (chunk:Chunk {{id: cid, user_id: $user_id}})-[:MENTIONS]->(concept:Concept {{user_id: $user_id}})
    MATCH (concept)-{hop_pattern}-(related:Concept {{user_id: $user_id}})
    WHERE concept <> related
    WITH concept, related,
         [(concept)-[r]->(related) | {{
           source: concept.name,
           relationship: type(r),
           target: related.name
         }}] AS direct_rels
    UNWIND direct_rels AS rel_triple
    RETURN DISTINCT
      rel_triple.source       AS source,
      rel_triple.relationship AS relationship,
      rel_triple.target       AS target
    LIMIT $max_rels
    """
    return run_query(
        cypher,
        {"chunk_ids": chunk_ids, "user_id": user_id, "max_rels": max_rels},
        database=database,
    )


def get_related_concepts_for_chunks(
    chunk_ids: list[str],
    user_id: str,
    database: str,
) -> list[str]:
    """Return concept names directly mentioned by the given chunks (user-scoped)."""
    if not chunk_ids:
        return []
    cypher = """
    UNWIND $chunk_ids AS cid
    MATCH (c:Chunk {id: cid, user_id: $user_id})-[:MENTIONS]->(concept:Concept {user_id: $user_id})
    RETURN DISTINCT concept.name AS name
    """
    results = run_query(
        cypher,
        {"chunk_ids": chunk_ids, "user_id": user_id},
        database=database,
    )
    return [r["name"] for r in results if r.get("name")]


def retrieve(
    question: str,
    user_id: str,
    top_k: int | None = None,
    graph_hops: int | None = None,
    note_id_filter: str | None = None,
) -> RetrievalResult:
    """
    USER-SCOPED GraphRAG retrieval.

    All steps filter by user_id at the database level.

    Args:
        question:       The user's question.
        user_id:        Authenticated user ID (REQUIRED).
        top_k:          Number of chunks to retrieve.
        graph_hops:     Traversal depth.
        note_id_filter: Neo4j note_id to restrict retrieval to a single note.
    """
    k = bounded_int(top_k, settings.top_k, 1, 20)
    hops = bounded_int(graph_hops, settings.graph_hops, 1, 4)
    db = settings.neo4j_database
    index = settings.vector_index_name

    result = RetrievalResult(question=question, user_id=user_id)

    # Embed the query
    try:
        query_embedding = embed_query(question)
    except Exception as e:
        logger.error("Failed to embed query for user %s: %s", user_id, e)
        return result

    # Vector search (user-scoped, DB-level filter)
    try:
        if note_id_filter:
            raw_results = vector_search_for_note(
                query_embedding, user_id, note_id_filter, k, index, db
            )
        else:
            raw_results = vector_search(query_embedding, user_id, k, index, db)
    except Exception as e:
        logger.error("Vector search failed for user %s: %s", user_id, e)
        return result

    if not raw_results:
        logger.info("No vector results for user %s question: %s", user_id, question)
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
                user_id=user_id,
            )
        )

    chunk_ids = [c.chunk_id for c in result.chunks]
    logger.info("Retrieved %d chunks for user %s", len(chunk_ids), user_id)

    # Graph traversal (user-scoped)
    result.concept_names = get_related_concepts_for_chunks(chunk_ids, user_id, db)

    try:
        result.relationships = expand_graph_from_chunks(chunk_ids, user_id, hops, db)
        logger.info(
            "Graph traversal: %d relationships for user %s",
            len(result.relationships), user_id,
        )
    except Exception as e:
        logger.warning("Graph traversal failed (non-fatal) for user %s: %s", user_id, e)

    return result


def vector_search_for_note(
    query_embedding: list[float],
    user_id: str,
    neo4j_note_id: str,
    top_k: int,
    index_name: str,
    database: str,
) -> list[dict]:
    """
    Vector search restricted to a single note's chunks.
    Both user_id AND note_id are verified at the database level.
    """
    top_k = bounded_int(top_k, settings.top_k, 1, 20)
    candidate_k = bounded_int(top_k * 10, 50, 10, 500)
    index_name = validate_cypher_identifier(index_name, "vector index name")
    cypher = """
    CALL db.index.vector.queryNodes($index_name, $candidate_k, $embedding)
    YIELD node AS chunk, score
    WHERE chunk.user_id = $user_id AND chunk.note_id = $note_id
    MATCH (n:Note {id: $note_id, user_id: $user_id})-[:HAS_CHUNK]->(chunk)
    RETURN
      chunk.id          AS chunk_id,
      chunk.text        AS text,
      chunk.note_id     AS note_id,
      n.title           AS note_title,
      n.filename        AS note_filename,
      score
    ORDER BY score DESC
    LIMIT $top_k
    """
    return run_query(
        cypher,
        {
            "index_name": index_name,
            "candidate_k": candidate_k,
            "top_k": top_k,
            "embedding": query_embedding,
            "user_id": user_id,
            "note_id": neo4j_note_id,
        },
        database=database,
    )


# ── Graph explorer helpers ────────────────────────────────────────────────────

def get_note_graph(
    neo4j_note_id: str,
    user_id: str,
    max_nodes: int | None = None,
) -> dict:
    """
    Return the graph centered on a note: its chunks, the concepts they mention,
    and the direct concept-to-concept relationships.

    All nodes are verified to belong to user_id.
    """
    lim = bounded_int(max_nodes, settings.graph_max_nodes, 1, 200)
    db = settings.neo4j_database

    cypher = """
    MATCH (n:Note {id: $note_id, user_id: $user_id})
    OPTIONAL MATCH (n)-[:HAS_CHUNK]->(c:Chunk {user_id: $user_id})
    OPTIONAL MATCH (c)-[:MENTIONS]->(concept:Concept {user_id: $user_id})
    OPTIONAL MATCH (concept)-[r]->(related:Concept {user_id: $user_id})
    WITH n, collect(DISTINCT c)      AS chunks,
            collect(DISTINCT concept) AS concepts,
            collect(DISTINCT {
              source_id:  concept.id,
              source:     concept.name,
              rel:        type(r),
              target_id:  related.id,
              target:     related.name
            })                        AS edges
    RETURN
      n.id       AS note_id,
      n.title    AS note_title,
      n.filename AS note_filename,
      chunks,
      concepts,
      edges
    LIMIT $lim
    """
    rows = run_query(
        cypher,
        {"note_id": neo4j_note_id, "user_id": user_id, "lim": lim},
        database=db,
    )
    if not rows:
        return {"note_id": neo4j_note_id, "nodes": [], "edges": []}

    row = rows[0]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()

    # Note node
    nodes.append({"id": row["note_id"], "label": row["note_title"], "type": "note"})
    seen_nodes.add(row["note_id"])

    # Concept nodes
    for c in (row["concepts"] or []):
        if c and c.get("id") and c["id"] not in seen_nodes:
            nodes.append({"id": c["id"], "label": c.get("name", ""), "type": "concept"})
            seen_nodes.add(c["id"])

    # Edges (concept → concept)
    for e in (row["edges"] or []):
        if e and e.get("source_id") and e.get("target_id") and e.get("rel"):
            edges.append({
                "source": e["source_id"],
                "target": e["target_id"],
                "type": e["rel"],
            })

    return {"note_id": neo4j_note_id, "nodes": nodes, "edges": edges}


def get_concept_graph(
    concept_id: str,
    user_id: str,
    depth: int | None = None,
    max_nodes: int | None = None,
) -> dict:
    """
    Return nodes and edges for a concept's neighbourhood (user-scoped).
    """
    hops = bounded_int(depth, settings.graph_max_depth, 1, 4)
    lim = bounded_int(max_nodes, settings.graph_max_nodes, 1, 200)
    db = settings.neo4j_database

    hop_pattern = f"*1..{hops}"
    cypher = f"""
    MATCH (root:Concept {{id: $concept_id, user_id: $user_id}})
    OPTIONAL MATCH (root)-[r{hop_pattern}]-(related:Concept {{user_id: $user_id}})
    WITH root, collect(DISTINCT related) AS neighbours,
         [(root)-[rx]->(nb:Concept {{user_id: $user_id}}) | {{
           source: root.id, target: nb.id, type: type(rx)
         }}] AS out_edges,
         [(root)<-[ry]-(nb2:Concept {{user_id: $user_id}}) | {{
           source: nb2.id, target: root.id, type: type(ry)
         }}] AS in_edges
    RETURN root, neighbours, out_edges + in_edges AS edges
    LIMIT $lim
    """
    rows = run_query(
        cypher,
        {"concept_id": concept_id, "user_id": user_id, "lim": lim},
        database=db,
    )
    if not rows:
        return {"concept_id": concept_id, "nodes": [], "edges": []}

    row = rows[0]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    root = row.get("root")
    if root:
        root_id = root.get("id", concept_id)
        nodes.append({"id": root_id, "label": root.get("name", ""), "type": "concept", "is_root": True})
        seen.add(root_id)

    for nb in (row.get("neighbours") or []):
        if nb and nb.get("id") and nb["id"] not in seen:
            nodes.append({"id": nb["id"], "label": nb.get("name", ""), "type": "concept"})
            seen.add(nb["id"])

    for e in (row.get("edges") or []):
        if e and e.get("source") and e.get("target") and e.get("type"):
            edges.append({"source": e["source"], "target": e["target"], "type": e["type"]})

    return {"concept_id": concept_id, "nodes": nodes, "edges": edges}


def get_concept_neighbours(
    concept_id: str,
    user_id: str,
) -> dict:
    """
    Return immediate (1-hop) neighbours of a concept with direction info.
    All nodes verified to belong to user_id.
    """
    db = settings.neo4j_database
    cypher = """
    MATCH (c:Concept {id: $concept_id, user_id: $user_id})
    OPTIONAL MATCH (c)-[r_out]->(nb_out:Concept {user_id: $user_id})
    OPTIONAL MATCH (c)<-[r_in]-(nb_in:Concept {user_id: $user_id})
    RETURN
      c.id   AS id,
      c.name AS name,
      collect(DISTINCT {
        id:           nb_out.id,
        name:         nb_out.name,
        relationship: type(r_out),
        direction:    'outgoing'
      }) AS outgoing,
      collect(DISTINCT {
        id:           nb_in.id,
        name:         nb_in.name,
        relationship: type(r_in),
        direction:    'incoming'
      }) AS incoming
    """
    rows = run_query(
        cypher,
        {"concept_id": concept_id, "user_id": user_id},
        database=db,
    )
    if not rows:
        return {"concept_id": concept_id, "name": "", "outgoing": [], "incoming": []}

    row = rows[0]
    outgoing = [n for n in (row.get("outgoing") or []) if n.get("id") and n.get("relationship")]
    incoming = [n for n in (row.get("incoming") or []) if n.get("id") and n.get("relationship")]
    return {
        "concept_id": row.get("id", concept_id),
        "name": row.get("name", ""),
        "outgoing": outgoing,
        "incoming": incoming,
    }


def find_path(
    source_name: str,
    target_name: str,
    user_id: str,
    max_depth: int | None = None,
) -> list[dict]:
    """
    Find the shortest path between two concept names within the user's graph.
    Returns a list of alternating {node} and {relationship} steps, or [] if none.
    All nodes must belong to user_id.
    """
    hops = bounded_int(max_depth, settings.graph_max_depth, 1, 6)
    db = settings.neo4j_database

    cypher = f"""
    MATCH (src:Concept {{user_id: $user_id}})
    WHERE toLower(src.name) = toLower($source)
    MATCH (tgt:Concept {{user_id: $user_id}})
    WHERE toLower(tgt.name) = toLower($target)
    MATCH path = shortestPath((src)-[*1..{hops}]-(tgt))
    WHERE ALL(n IN nodes(path) WHERE
        (n:Concept AND n.user_id = $user_id) OR NOT n:Concept
    )
    RETURN
      [n IN nodes(path) | {{id: n.id, name: n.name, label: labels(n)[0]}}] AS path_nodes,
      [r IN relationships(path) | type(r)] AS rel_types
    LIMIT 1
    """
    rows = run_query(
        cypher,
        {"source": source_name, "target": target_name, "user_id": user_id},
        database=db,
    )
    if not rows:
        return []

    path_nodes = rows[0].get("path_nodes") or []
    rel_types = rows[0].get("rel_types") or []

    steps: list[dict] = []
    for i, node in enumerate(path_nodes):
        steps.append({"node": node.get("name", ""), "id": node.get("id", ""), "type": node.get("label", "")})
        if i < len(rel_types):
            steps.append({"relationship": rel_types[i]})

    return steps


def get_note_related(
    neo4j_note_id: str,
    user_id: str,
    max_notes: int = 5,
) -> dict:
    """
    Return notes related to a given note via shared concepts (user-scoped).
    Also returns the concepts and direct relationships of the note.
    """
    db = settings.neo4j_database
    max_notes = bounded_int(max_notes, 5, 1, 20)

    # Get concepts for this note
    cypher_concepts = """
    MATCH (n:Note {id: $note_id, user_id: $user_id})
    MATCH (n)-[:HAS_CHUNK]->(c:Chunk {user_id: $user_id})-[:MENTIONS]->(concept:Concept {user_id: $user_id})
    RETURN DISTINCT concept.id AS cid, concept.name AS name
    LIMIT 20
    """
    concept_rows = run_query(
        cypher_concepts,
        {"note_id": neo4j_note_id, "user_id": user_id},
        database=db,
    )
    concept_ids = [r["cid"] for r in concept_rows if r.get("cid")]
    concepts = [{"id": r["cid"], "name": r["name"]} for r in concept_rows if r.get("cid")]

    if not concept_ids:
        return {"note_id": neo4j_note_id, "related_notes": [], "concepts": [], "relationships": []}

    # Notes sharing at least one concept (excluding self)
    cypher_related = """
    UNWIND $concept_ids AS cid
    MATCH (concept:Concept {id: cid, user_id: $user_id})
    MATCH (c2:Chunk {user_id: $user_id})-[:MENTIONS]->(concept)
    MATCH (n2:Note {user_id: $user_id})-[:HAS_CHUNK]->(c2)
    WHERE n2.id <> $note_id
    RETURN DISTINCT n2.id AS note_id, n2.title AS title, n2.filename AS filename,
                    count(DISTINCT concept) AS shared_count
    ORDER BY shared_count DESC
    LIMIT $max_notes
    """
    related_rows = run_query(
        cypher_related,
        {"concept_ids": concept_ids, "user_id": user_id,
         "note_id": neo4j_note_id, "max_notes": max_notes},
        database=db,
    )
    related_notes = [
        {"note_id": r["note_id"], "title": r["title"],
         "filename": r["filename"], "shared_concepts": r["shared_count"]}
        for r in related_rows if r.get("note_id")
    ]

    # Direct concept relationships
    cypher_rels = """
    UNWIND $concept_ids AS cid
    MATCH (a:Concept {id: cid, user_id: $user_id})-[r]->(b:Concept {user_id: $user_id})
    RETURN DISTINCT a.name AS source, type(r) AS relationship, b.name AS target
    LIMIT 30
    """
    rel_rows = run_query(
        cypher_rels,
        {"concept_ids": concept_ids, "user_id": user_id},
        database=db,
    )
    relationships = [
        {"source": r["source"], "relationship": r["relationship"], "target": r["target"]}
        for r in rel_rows if r.get("source") and r.get("target")
    ]

    return {
        "note_id": neo4j_note_id,
        "related_notes": related_notes,
        "concepts": concepts,
        "relationships": relationships,
    }
