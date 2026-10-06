(() => {
  function initSidebarSearch() {
    document.querySelectorAll(".side-search").forEach((form) => {
      const input = form.querySelector("input[type='search']");
      if (!input) return;
      input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") input.value = "";
      });
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const query = input.value.trim();
        location.href = query ? `/notes?q=${encodeURIComponent(query)}` : "/notes";
      });
    });
  }

  async function runGlobalSearch(query, target) {
    if (!query) {
      target.innerHTML = "";
      return;
    }
    target.innerHTML = '<p class="status-line">Searching...</p>';
    try {
      const data = await VG.apiFetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
      target.innerHTML = renderResults(data.results || []);
    } catch (err) {
      target.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    }
  }

  function renderResults(results) {
    if (!results.length) return '<p class="empty-state">No matches found.</p>';
    return `<ul class="result-list">${results.map((item) => `
      <li>
        <a href="/notes/${VG.escapeHtml(item.id)}"><strong>${VG.escapeHtml(item.title)}</strong></a>
        <p class="muted">${VG.escapeHtml(item.snippet || item.filename || "")}</p>
      </li>
    `).join("")}</ul>`;
  }

  initSidebarSearch();
  window.VGSearch = { runGlobalSearch };
})();
