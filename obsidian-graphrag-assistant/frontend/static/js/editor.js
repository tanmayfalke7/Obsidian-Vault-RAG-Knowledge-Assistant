(() => {
  const page = document.querySelector("[data-notes-page]");
  if (!page) return;

  const els = {
    list: document.querySelector("#note-list"),
    search: document.querySelector("#note-search"),
    sort: document.querySelector("#note-sort"),
    title: document.querySelector("#note-title"),
    folder: document.querySelector("#folder-select"),
    content: document.querySelector("#note-content"),
    preview: document.querySelector("#note-preview"),
    dirty: document.querySelector("#dirty-indicator"),
    save: document.querySelector("#save-note-btn"),
    reindex: document.querySelector("#reindex-note-btn"),
    delete: document.querySelector("#delete-note-btn"),
    inspector: document.querySelector("#note-inspector"),
    ragForm: document.querySelector("#note-rag-form"),
    ragQuestion: document.querySelector("#note-rag-question"),
    ragAnswer: document.querySelector("#note-rag-answer")
  };

  const state = {
    current: null,
    dirty: false,
    saving: false,
    saveVersion: 0,
    folderId: new URLSearchParams(location.search).get("folder") || "",
    page: 1
  };

  function setDirty(value) {
    state.dirty = value;
    els.dirty.hidden = !value;
  }

  function setEditorDisabled(value) {
    [els.title, els.folder, els.content, els.save, els.reindex, els.delete].forEach((el) => {
      if (el) el.disabled = value;
    });
  }

  async function loadNotes() {
    const [sort, order] = (els.sort.value || "updated_at:desc").split(":");
    const params = new URLSearchParams({
      all_folders: state.folderId ? "false" : "true",
      sort,
      order: order || "desc",
      page: String(state.page),
      page_size: "50"
    });
    if (state.folderId) params.set("folder_id", state.folderId);
    if (els.search.value.trim()) params.set("search", els.search.value.trim());

    els.list.innerHTML = '<p class="status-line">Loading notes...</p>';
    try {
      const data = await VG.apiFetch(`/api/notes?${params.toString()}`);
      renderNoteList(data.items || [], data);
    } catch (err) {
      els.list.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    }
  }

  function renderNoteList(notes, pageData) {
    if (!notes.length) {
      els.list.innerHTML = '<p class="empty-state">No notes match this view.</p>';
      return;
    }
    const items = notes.map((note) => `
      <button class="note-item ${state.current && state.current.id === note.id ? "active" : ""}" type="button" data-note-id="${VG.escapeHtml(note.id)}">
        <strong>${VG.escapeHtml(note.title)}</strong>
        <span class="note-meta">
          <span>${VG.escapeHtml(note.source_type || note.filename || "note")}</span>
          <span>${VG.formatDate(note.updated_at)}</span>
        </span>
      </button>
    `).join("");
    const paging = pageData.pages > 1
      ? `<div class="panel-toolbar"><button class="button button-secondary" type="button" data-page-prev ${pageData.page <= 1 ? "disabled" : ""}>Previous</button><span class="muted">Page ${pageData.page} of ${pageData.pages}</span><button class="button button-secondary" type="button" data-page-next ${pageData.page >= pageData.pages ? "disabled" : ""}>Next</button></div>`
      : "";
    els.list.innerHTML = `${items}${paging}`;
  }

  async function openNote(noteId, push = true) {
    if (state.dirty && !confirm("You have unsaved changes. Open another note anyway?")) return;
    setEditorDisabled(true);
    els.preview.innerHTML = '<p class="status-line">Loading note...</p>';
    try {
      const note = await VG.apiFetch(`/api/notes/${encodeURIComponent(noteId)}`);
      state.current = note;
      els.title.value = note.title || "";
      els.folder.value = note.folder_id || "";
      els.content.value = note.content || "";
      setDirty(false);
      renderPreview();
      renderInspector(note);
      if (els.ragForm) els.ragForm.hidden = false;
      if (els.ragAnswer) els.ragAnswer.innerHTML = "";
      if (push) history.replaceState(null, "", `/notes/${encodeURIComponent(note.id)}`);
      await loadNotes();
    } catch (err) {
      VG.toast(err.message, "error");
      els.preview.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    } finally {
      setEditorDisabled(false);
    }
  }

  function renderPreview() {
    const text = els.content.value || "";
    if (!window.marked || !window.DOMPurify) {
      els.preview.textContent = text;
      return;
    }
    marked.setOptions({ breaks: true, gfm: true, mangle: false, headerIds: false });
    const html = marked.parse(text);
    els.preview.innerHTML = DOMPurify.sanitize(html, {
      FORBID_TAGS: ["script", "iframe", "object", "embed"],
      FORBID_ATTR: ["onerror", "onload", "onclick"]
    });
    els.preview.querySelectorAll("a").forEach((link) => {
      const href = link.getAttribute("href") || "";
      if (/^\s*javascript:/i.test(href)) link.removeAttribute("href");
      link.rel = "noopener noreferrer";
      link.target = "_blank";
    });
  }

  function renderInspector(note) {
    const wikiLinks = [...(note.content || "").matchAll(/\[\[([^\]]+)\]\]/g)].map((match) => match[1]);
    els.inspector.innerHTML = `
      <dl class="meta-list">
        <div><dt>Filename</dt><dd>${VG.escapeHtml(note.filename)}</dd></div>
        <div><dt>Source</dt><dd>${VG.escapeHtml(note.source_type)}</dd></div>
        <div><dt>Updated</dt><dd>${VG.formatDate(note.updated_at)}</dd></div>
      </dl>
      <h3>Wiki Links</h3>
      <p>${wikiLinks.length ? wikiLinks.map((link) => `<span class="wiki-pill">${VG.escapeHtml(link)}</span>`).join(" ") : '<span class="muted">No wiki links in this note.</span>'}</p>
      <button class="button button-secondary" type="button" data-load-related>Load Related Knowledge</button>
      <div id="related-knowledge"></div>
    `;
  }

  async function createNote() {
    const title = "Untitled note";
    try {
      const note = await VG.apiFetch("/api/notes", {
        method: "POST",
        body: {
          title,
          filename: `untitled-${Date.now()}.md`,
          content: "# Untitled note\n\n",
          folder_id: state.folderId || null
        }
      });
      VG.toast("Note created.", "success");
      await openNote(note.id);
    } catch (err) {
      VG.toast(err.message, "error");
    }
  }

  async function saveNote({ silent = false } = {}) {
    if (!state.current || state.saving) return;
    const version = ++state.saveVersion;
    state.saving = true;
    els.save.disabled = true;
    els.save.textContent = silent ? "Autosaving..." : "Saving...";
    try {
      const note = await VG.apiFetch(`/api/notes/${encodeURIComponent(state.current.id)}`, {
        method: "PUT",
        body: {
          title: els.title.value.trim() || "Untitled note",
          content: els.content.value,
          folder_id: els.folder.value || null
        }
      });
      if (version === state.saveVersion) {
        state.current = note;
        setDirty(false);
        els.save.textContent = "Saved";
        if (!silent) VG.toast("Note saved.", "success");
        await loadNotes();
      }
    } catch (err) {
      els.save.textContent = "Save failed";
      VG.toast(err.message, "error");
    } finally {
      state.saving = false;
      setTimeout(() => {
        els.save.disabled = false;
        els.save.textContent = "Save";
      }, 700);
    }
  }

  const debouncedPreview = VG.debounce(renderPreview, 120);
  const debouncedAutosave = VG.debounce(() => {
    if (state.current && state.dirty) saveNote({ silent: true });
  }, 1500);

  function markChanged() {
    setDirty(true);
    debouncedPreview();
    debouncedAutosave();
  }

  async function reindexNote() {
    if (!state.current) return;
    els.reindex.disabled = true;
    els.reindex.textContent = "Indexing...";
    try {
      const result = await VG.apiFetch(`/api/notes/${encodeURIComponent(state.current.id)}/reindex`, { method: "POST" });
      if (result.ingested) VG.toast(`Indexed ${result.chunks_created} chunks.`, "success");
      else VG.toast((result.errors || []).join(", ") || "Indexing completed with warnings.", "error");
    } catch (err) {
      VG.toast(err.message, "error");
    } finally {
      els.reindex.disabled = false;
      els.reindex.textContent = "Reindex";
    }
  }

  async function deleteNote() {
    if (!state.current || !confirm(`Delete "${state.current.title}"? This cannot be undone.`)) return;
    try {
      await VG.apiFetch(`/api/notes/${encodeURIComponent(state.current.id)}`, { method: "DELETE" });
      VG.toast("Note deleted.", "success");
      state.current = null;
      els.title.value = "";
      els.content.value = "";
      els.preview.innerHTML = '<p class="empty-state">Select or create a note.</p>';
      els.inspector.innerHTML = '<p class="muted">Open a note to inspect source metadata, wiki-links, and graph context.</p>';
      if (els.ragForm) els.ragForm.hidden = true;
      await loadNotes();
      history.replaceState(null, "", "/notes");
    } catch (err) {
      VG.toast(err.message, "error");
    }
  }

  function insertMarkdown(pattern) {
    const start = els.content.selectionStart;
    const end = els.content.selectionEnd;
    const selected = els.content.value.slice(start, end);
    const [before, after = ""] = pattern.split("|");
    const text = `${before}${selected}${after}`;
    els.content.setRangeText(text, start, end, "select");
    els.content.focus();
    markChanged();
  }

  async function loadRelated() {
    if (!state.current) return;
    const target = document.querySelector("#related-knowledge");
    target.innerHTML = '<p class="status-line">Loading related graph evidence...</p>';
    try {
      const related = await VG.apiFetch(`/api/rag/note/${encodeURIComponent(state.current.id)}/related`);
      target.innerHTML = renderRelated(related);
    } catch (err) {
      target.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    }
  }

  function renderRelated(data) {
    const notes = (data.related_notes || []).map((note) => `<li><a href="/notes/${VG.escapeHtml(note.note_id)}">${VG.escapeHtml(note.title)}</a> <span class="badge">${note.shared_concepts} shared</span></li>`).join("");
    const concepts = (data.concepts || []).map((concept) => `<span class="wiki-pill">${VG.escapeHtml(concept.name)}</span>`).join(" ");
    const relationships = (data.relationships || []).map((rel) => `<div class="relationship-row"><strong>${VG.escapeHtml(rel.source)}</strong><span>${VG.escapeHtml(rel.relationship)}</span><strong>${VG.escapeHtml(rel.target)}</strong></div>`).join("");
    return `
      <h3>Related Notes</h3>
      <ul class="result-list">${notes || "<li>No related notes found.</li>"}</ul>
      <h3>Concepts</h3>
      <p>${concepts || '<span class="muted">No concepts found.</span>'}</p>
      <h3>Relationships</h3>
      ${relationships || '<p class="muted">No relationships found.</p>'}
    `;
  }

  async function askNote(event) {
    event.preventDefault();
    if (!state.current) return;
    const question = els.ragQuestion.value.trim();
    if (!question) {
      els.ragQuestion.focus();
      return;
    }
    const button = els.ragForm.querySelector("button[type='submit']");
    button.disabled = true;
    els.ragAnswer.innerHTML = '<p class="status-line">Running note-scoped GraphRAG...</p>';
    try {
      const result = await VG.apiFetch(`/api/rag/note/${encodeURIComponent(state.current.id)}/query`, {
        method: "POST",
        body: { question, top_k: 5 }
      });
      els.ragAnswer.innerHTML = renderRagMini(result);
    } catch (err) {
      els.ragAnswer.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  }

  function renderRagMini(result) {
    const sources = (result.sources || []).map((src) => `<li>${VG.escapeHtml(src.title || src.filename)} <span class="badge">${Number(src.score || 0).toFixed(2)}</span></li>`).join("");
    const rels = (result.relationships || []).map((rel) => `<div class="relationship-row"><strong>${VG.escapeHtml(rel.source)}</strong><span>${VG.escapeHtml(rel.relationship)}</span><strong>${VG.escapeHtml(rel.target)}</strong></div>`).join("");
    return `
      <section><h3>Answer</h3><div class="answer-content">${VG.escapeHtml(result.answer || "No answer returned.")}</div></section>
      <section><h3>Sources</h3><ul class="result-list">${sources || "<li>No sources returned.</li>"}</ul></section>
      <section><h3>Graph Evidence</h3>${rels || '<p class="muted">No graph relationships returned.</p>'}</section>
    `;
  }

  document.querySelector("#new-note-btn")?.addEventListener("click", createNote);
  els.save?.addEventListener("click", () => saveNote());
  els.reindex?.addEventListener("click", reindexNote);
  els.delete?.addEventListener("click", deleteNote);
  els.content?.addEventListener("input", markChanged);
  els.title?.addEventListener("input", markChanged);
  els.folder?.addEventListener("change", markChanged);
  els.search?.addEventListener("input", VG.debounce(loadNotes, 300));
  els.sort?.addEventListener("change", loadNotes);
  els.ragForm?.addEventListener("submit", askNote);

  document.querySelector(".editor-toolbar")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-insert]");
    if (button) insertMarkdown(button.dataset.insert);
  });

  els.list.addEventListener("click", (event) => {
    const noteButton = event.target.closest("[data-note-id]");
    if (noteButton) openNote(noteButton.dataset.noteId);
    if (event.target.closest("[data-page-prev]")) {
      state.page = Math.max(1, state.page - 1);
      loadNotes();
    }
    if (event.target.closest("[data-page-next]")) {
      state.page += 1;
      loadNotes();
    }
  });

  els.inspector.addEventListener("click", (event) => {
    if (event.target.closest("[data-load-related]")) loadRelated();
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveNote();
    }
  });

  document.addEventListener("vault:folder-selected", (event) => {
    state.folderId = event.detail.folderId || "";
    state.page = 1;
    loadNotes();
  });
  document.addEventListener("vault:notes-changed", loadNotes);
  document.addEventListener("vault:folders-changed", () => location.reload());

  const params = new URLSearchParams(location.search);
  const initialNoteId = page.dataset.initialNoteId || params.get("note");
  if (params.get("q")) els.search.value = params.get("q");
  loadNotes().then(() => {
    if (initialNoteId) openNote(initialNoteId, false);
    else if (params.get("new") === "1") createNote();
    else els.preview.innerHTML = '<p class="empty-state">Select or create a note.</p>';
    if (params.get("upload") === "1") document.querySelector("#note-upload")?.click();
  });
})();
