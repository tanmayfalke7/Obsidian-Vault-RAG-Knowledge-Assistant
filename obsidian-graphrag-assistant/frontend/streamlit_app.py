"""
Streamlit frontend for the Obsidian GraphRAG Knowledge Assistant.

Architecture:
  Streamlit → httpx → FastAPI → Neo4j + Gemini

All retrieval logic lives in FastAPI. This file is intentionally thin.
"""
import os
import httpx
import streamlit as st

# ── Configuration ─────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 120.0  # seconds — LLM generation can take a moment

st.set_page_config(
    page_title="Obsidian GraphRAG Assistant",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helper functions ───────────────────────────────────────────────────────────

def api_get(path: str) -> dict | list | None:
    """GET request to FastAPI. Returns None on error."""
    try:
        resp = httpx.get(f"{BACKEND_URL}{path}", timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, payload: dict) -> dict | None:
    """POST request to FastAPI. Returns None on error."""
    try:
        resp = httpx.post(
            f"{BACKEND_URL}{path}",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except httpx.HTTPStatusError as e:
        st.error(f"API returned error {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        st.error(f"Request failed: {e}")
        return None


def check_backend() -> bool:
    """Return True if FastAPI is reachable."""
    health = api_get("/health")
    return health is not None


@st.cache_data(ttl=30)
def fetch_stats() -> dict:
    data = api_get("/api/stats")
    if data is None:
        return {"notes": 0, "chunks": 0, "concepts": 0, "relationships": 0, "vector_index": "unknown"}
    return data


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧠 Obsidian GraphRAG")
    st.caption("Knowledge Assistant")
    st.divider()

    # Backend status
    backend_ok = check_backend()
    if backend_ok:
        st.success("✓ Backend connected")
    else:
        st.error("✗ Backend unavailable")
        st.info(
            "Start FastAPI with:\n```\n"
            ".venv\\Scripts\\uvicorn backend.main:app --reload\n```"
        )

    st.divider()

    # Knowledge base stats
    st.subheader("📊 Knowledge Base")
    if backend_ok:
        stats = fetch_stats()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Notes", stats.get("notes", 0))
            st.metric("Concepts", stats.get("concepts", 0))
        with col2:
            st.metric("Chunks", stats.get("chunks", 0))
            st.metric("Relations", stats.get("relationships", 0))

        idx_status = stats.get("vector_index", "unknown")
        colour = "green" if idx_status == "ONLINE" else "orange"
        st.markdown(
            f"Vector index: :{colour}[{idx_status}]"
        )

        if st.button("🔄 Refresh Stats"):
            st.cache_data.clear()
            st.rerun()

        st.divider()

        # Ingest button
        st.subheader("⚙️ Ingestion")
        reset_flag = st.checkbox("Reset existing data first", value=False)
        if st.button("📥 Ingest Vault", type="secondary"):
            with st.spinner("Ingesting vault... (this may take 1-2 minutes)"):
                result = api_post("/api/ingest", {"reset": reset_flag})
            if result:
                if result.get("success"):
                    st.success(
                        f"✓ Ingestion complete!\n"
                        f"Notes: {result['notes_processed']} | "
                        f"Chunks: {result['chunks_created']} | "
                        f"Embeddings: {result['embeddings_generated']}"
                    )
                    st.cache_data.clear()
                else:
                    st.warning("Ingestion completed with errors.")
                    for err in result.get("errors", []):
                        st.error(err)

    else:
        st.info("Connect backend to see stats.")

    st.divider()

    # Graph explorer
    st.subheader("🔍 Graph Explorer")
    concept_input = st.text_input(
        "Explore concept",
        placeholder="e.g. RAG, Embeddings, Neo4j",
        key="graph_explorer_input",
    )
    if st.button("Explore", key="explore_btn") and concept_input.strip():
        with st.spinner("Querying graph..."):
            data = api_get(f"/api/graph/{concept_input.strip()}")
        if data is None:
            st.error("Backend unavailable.")
        elif not data.get("found"):
            st.warning(f"Concept '{concept_input}' not found in graph.")
        else:
            st.markdown(f"**{data['concept']}**")
            neighbours = data.get("neighbours", [])
            if neighbours:
                outgoing = [n for n in neighbours if n["direction"] == "outgoing"]
                incoming = [n for n in neighbours if n["direction"] == "incoming"]
                if outgoing:
                    st.markdown("*Outgoing:*")
                    for n in outgoing:
                        st.markdown(f"  → `{n['relationship']}` → **{n['concept']}**")
                if incoming:
                    st.markdown("*Incoming:*")
                    for n in incoming:
                        st.markdown(f"  ← `{n['relationship']}` ← **{n['concept']}**")
            else:
                st.info("No neighbours found.")


# ── Main area ─────────────────────────────────────────────────────────────────
st.title("🧠 Obsidian Knowledge Assistant")
st.caption("Powered by GraphRAG • Neo4j • Gemini")

if not backend_ok:
    st.warning(
        "⚠️ Backend is not running. Start FastAPI first:\n"
        "```\n.venv\\Scripts\\uvicorn backend.main:app --reload\n```"
    )
    st.stop()

# Example prompts
with st.expander("💡 Example questions", expanded=False):
    examples = [
        "What is RAG?",
        "How are embeddings related to vector search?",
        "What is the relationship between vector search and vector databases?",
        "How does GraphRAG improve traditional RAG?",
        "What role does Neo4j play in this system?",
        "What should I learn before GraphRAG?",
        "How are RAG, embeddings, vector search and Neo4j connected?",
        "Find the relationship path from RAG to semantic search.",
        "What technologies are used by the JARVIS project?",
        "Explain the difference between RAG and GraphRAG.",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex[:20]}"):
            st.session_state["prefill_question"] = ex
            st.rerun()

# ── Chat interface ─────────────────────────────────────────────────────────────

# Initialise chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("📄 Sources", expanded=False):
                for src in msg["sources"]:
                    score_str = f" — score: {src['score']:.3f}" if src.get("score") else ""
                    st.markdown(f"• **{src.get('title', src.get('filename', '?'))}** "
                                f"`{src.get('filename', '')}`{score_str}")
        if msg.get("relationships"):
            with st.expander("🕸️ Graph context", expanded=False):
                for rel in msg["relationships"]:
                    st.markdown(
                        f"**{rel['source']}** → `{rel['relationship']}` → **{rel['target']}**"
                    )

# Chat input — handle prefill from example buttons
prefill = st.session_state.pop("prefill_question", None)
user_input = st.chat_input("Ask anything about the knowledge base…")
if prefill and not user_input:
    user_input = prefill

if user_input:
    # Show user message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Query the backend
    with st.chat_message("assistant"):
        with st.spinner("Searching knowledge graph…"):
            response = api_post("/api/query", {"question": user_input, "top_k": 5})

        if response is None:
            answer = "⚠️ Backend unavailable. Please start FastAPI."
            sources = []
            relationships = []
        else:
            answer = response.get("answer", "No answer returned.")
            sources = response.get("sources", [])
            relationships = response.get("relationships", [])

        st.markdown(answer)

        if sources:
            with st.expander(f"📄 Sources ({len(sources)})", expanded=True):
                for src in sources:
                    score_str = (
                        f" — relevance: {src['score']:.3f}"
                        if src.get("score")
                        else ""
                    )
                    st.markdown(
                        f"• **{src.get('title', '?')}** "
                        f"`{src.get('filename', '')}`{score_str}"
                    )

        if relationships:
            with st.expander(f"🕸️ Graph relationships ({len(relationships)})", expanded=True):
                for rel in relationships[:10]:
                    st.markdown(
                        f"**{rel['source']}** → `{rel['relationship']}` → **{rel['target']}**"
                    )

        chunks_used = response.get("chunks_used", 0) if response else 0
        st.caption(f"Retrieved {chunks_used} chunks from knowledge graph")

    # Save to history
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "relationships": relationships,
    })

# Footer
st.divider()
st.caption(
    "Obsidian GraphRAG Knowledge Assistant • "
    "Neo4j + Gemini • "
    "Vector Search + Knowledge Graph Traversal"
)
