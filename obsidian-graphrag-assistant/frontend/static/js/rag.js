(() => {
  const page = document.querySelector("[data-rag-page]");
  if (!page) return;

  const form = document.querySelector("#rag-form");
  const question = document.querySelector("#rag-question");
  const topK = document.querySelector("#rag-top-k");
  const answer = document.querySelector("#rag-answer");
  const sources = document.querySelector("#rag-sources");
  const steps = [...document.querySelectorAll("#rag-pipeline [data-step]")];

  function setPipeline(activeIndex = -1, done = false) {
    steps.forEach((step, index) => {
      step.classList.toggle("active", index === activeIndex && !done);
      step.classList.toggle("done", done || index < activeIndex);
    });
  }

  function renderAnswer(result) {
    answer.classList.remove("muted");
    answer.textContent = result.answer || "No answer returned.";
    const sourceCards = (result.sources || []).map((source) => `
      <article class="source-card">
        <strong>${VG.escapeHtml(source.title || source.filename)}</strong>
        <p class="muted">${VG.escapeHtml(source.filename)} · score ${Number(source.score || 0).toFixed(3)}</p>
        <a class="button button-secondary" href="/notes/${VG.escapeHtml(source.note_id)}">Open Source</a>
      </article>
    `).join("");
    const concepts = (result.concepts || []).map((concept) => `<span class="wiki-pill">${VG.escapeHtml(concept)}</span>`).join(" ");
    const relationships = (result.relationships || []).map((rel) => `
      <div class="triple-row relationship-row">
        <strong>${VG.escapeHtml(rel.source)}</strong>
        <span>${VG.escapeHtml(rel.relationship)}</span>
        <strong>${VG.escapeHtml(rel.target)}</strong>
      </div>
    `).join("");
    const chunks = (result.retrieved_chunks || []).map((chunk) => `
      <article class="source-card">
        <strong>${VG.escapeHtml(chunk.note_title || chunk.note_filename)}</strong>
        <p>${VG.escapeHtml(chunk.text || "").slice(0, 420)}</p>
      </article>
    `).join("");
    sources.innerHTML = `
      <h3>Sources</h3>
      ${sourceCards || '<p class="muted">No source notes returned.</p>'}
      <h3>Retrieved Concepts</h3>
      <p>${concepts || '<span class="muted">No concepts returned.</span>'}</p>
      <h3>Relationships</h3>
      ${relationships || '<p class="muted">No graph relationships returned.</p>'}
      <h3>Retrieved Chunks</h3>
      ${chunks || '<p class="muted">No chunks returned.</p>'}
    `;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = question.value.trim();
    if (!text) {
      question.focus();
      return;
    }
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    answer.classList.add("muted");
    answer.textContent = "Running GraphRAG...";
    sources.innerHTML = '<p class="status-line">Retrieving sources and graph evidence...</p>';
    setPipeline(0);
    const pipelineTimer = setInterval(() => {
      const current = steps.findIndex((step) => step.classList.contains("active"));
      setPipeline(Math.min(current + 1, steps.length - 1));
    }, 650);

    try {
      const result = await VG.apiFetch("/api/rag/query", {
        method: "POST",
        body: {
          question: text,
          top_k: Number(topK.value || 5)
        }
      });
      clearInterval(pipelineTimer);
      setPipeline(steps.length - 1, true);
      renderAnswer(result);
      if (result.has_error) VG.toast("GraphRAG returned a partial answer.", "error");
    } catch (err) {
      clearInterval(pipelineTimer);
      setPipeline(-1);
      answer.textContent = "Query failed.";
      sources.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  });
})();
