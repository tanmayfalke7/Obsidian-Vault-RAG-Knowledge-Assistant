(() => {
  const statusMessages = {
    400: "The request could not be completed.",
    401: "Your session has expired. Please sign in again.",
    403: "You do not have access to that action.",
    404: "That item could not be found.",
    409: "That name or action conflicts with existing vault data.",
    413: "The file is too large.",
    422: "Please check the highlighted values and try again.",
    429: "Too many requests. Please wait a moment.",
    500: "The server hit an unexpected error.",
    503: "The graph or AI service is currently unavailable."
  };

  class ApiError extends Error {
    constructor(message, status, detail) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  }

  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const init = {
      credentials: "same-origin",
      ...options,
      headers
    };

    if (init.body && !(init.body instanceof FormData) && typeof init.body !== "string") {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(init.body);
    }
    headers.set("Accept", "application/json");

    const response = await fetch(url, init);
    if (response.status === 401 && !location.pathname.startsWith("/login")) {
      toast("Session expired. Redirecting to sign in.", "error");
      setTimeout(() => { location.href = "/login"; }, 500);
    }
    if (!response.ok) {
      const detail = await readError(response);
      throw new ApiError(detail || statusMessages[response.status] || "Request failed.", response.status, detail);
    }
    if (response.status === 204) return null;
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  }

  async function readError(response) {
    try {
      const data = await response.json();
      if (Array.isArray(data.detail)) {
        return data.detail.map((item) => item.msg || item.message || String(item)).join(" ");
      }
      return data.detail || data.message || statusMessages[response.status];
    } catch {
      return statusMessages[response.status];
    }
  }

  function toast(message, type = "info") {
    const root = document.querySelector("#toast-root") || createToastRoot();
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.textContent = message;
    root.append(item);
    setTimeout(() => item.remove(), 4200);
  }

  function createToastRoot() {
    const root = document.createElement("div");
    root.id = "toast-root";
    root.className = "toast-root";
    root.setAttribute("aria-live", "polite");
    document.body.append(root);
    return root;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function debounce(fn, delay = 300) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  function bytes(value) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  async function initAuthForms() {
    document.querySelectorAll("[data-auth-form]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const mode = form.dataset.authForm;
        const error = form.querySelector("[data-form-error]");
        const button = form.querySelector("button[type='submit']");
        error.textContent = "";

        if (!form.reportValidity()) return;
        const data = Object.fromEntries(new FormData(form).entries());
        if (mode === "register" && data.password !== data.confirm_password) {
          error.textContent = "Passwords do not match.";
          return;
        }

        button.disabled = true;
        button.textContent = mode === "login" ? "Signing in..." : "Creating account...";
        try {
          if (mode === "register") {
            await apiFetch("/api/auth/register", {
              method: "POST",
              body: {
                name: data.name,
                email: data.email,
                phone: data.phone,
                password: data.password
              }
            });
            await apiFetch("/api/auth/login", {
              method: "POST",
              body: { email: data.email, password: data.password }
            });
          } else {
            await apiFetch("/api/auth/login", {
              method: "POST",
              body: { email: data.email, password: data.password }
            });
          }
          location.href = "/dashboard";
        } catch (err) {
          error.textContent = err.message || "Authentication failed.";
        } finally {
          button.disabled = false;
          button.textContent = mode === "login" ? "Sign in" : "Create account";
        }
      });
    });
  }

  function initLogout() {
    document.querySelectorAll("[data-logout]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await apiFetch("/api/auth/logout", { method: "POST" });
          location.href = "/login";
        } catch (err) {
          toast(err.message || "Logout failed.", "error");
          button.disabled = false;
        }
      });
    });
  }

  const folderState = {
    tree: [],
    collapsed: new Set(JSON.parse(localStorage.getItem("vg-collapsed-folders") || "[]"))
  };

  async function loadFolderTree() {
    const root = document.querySelector("#global-folder-tree");
    if (!root) return [];
    try {
      folderState.tree = await apiFetch("/api/folders/tree");
      renderFolderTree(root, folderState.tree);
      return folderState.tree;
    } catch (err) {
      root.innerHTML = `<p class="status-line error">${escapeHtml(err.message)}</p>`;
      return [];
    }
  }

  function renderFolderTree(root, nodes) {
    const children = nodes.map((node) => renderFolderNode(node)).join("");
    root.classList.remove("muted-tree");
    root.innerHTML = `
      <div class="tree-row" data-folder-id="">
        <span aria-hidden="true">⌂</span>
        <strong>My Notes</strong>
      </div>
      <div class="tree-children">${children || '<p class="muted">No folders yet.</p>'}</div>
    `;
  }

  function renderFolderNode(node) {
    const hasChildren = node.children && node.children.length;
    const collapsed = folderState.collapsed.has(node.id);
    const children = hasChildren && !collapsed
      ? `<div class="tree-children">${node.children.map((child) => renderFolderNode(child)).join("")}</div>`
      : "";
    return `
      <div class="tree-row" data-folder-id="${escapeHtml(node.id)}">
        <button type="button" data-folder-toggle="${escapeHtml(node.id)}" aria-label="Toggle ${escapeHtml(node.name)}">${hasChildren ? (collapsed ? "+" : "-") : ""}</button>
        <span class="folder-name">${escapeHtml(node.name)}</span>
        <span class="badge">${node.note_count || 0}</span>
        <span class="folder-ops">
          <button type="button" data-folder-add="${escapeHtml(node.id)}" title="New child folder" aria-label="New child folder">+</button>
          <button type="button" data-folder-rename="${escapeHtml(node.id)}" title="Rename folder" aria-label="Rename folder">✎</button>
          <button type="button" data-folder-delete="${escapeHtml(node.id)}" title="Delete folder" aria-label="Delete folder">×</button>
        </span>
      </div>
      ${children}
    `;
  }

  function initFolderTree() {
    const root = document.querySelector("#global-folder-tree");
    if (!root) return;
    loadFolderTree();
    root.addEventListener("click", async (event) => {
      const toggle = event.target.closest("[data-folder-toggle]");
      const create = event.target.closest("[data-folder-add]");
      const rename = event.target.closest("[data-folder-rename]");
      const del = event.target.closest("[data-folder-delete]");
      const row = event.target.closest("[data-folder-id]");

      if (toggle) {
        event.stopPropagation();
        const id = toggle.dataset.folderToggle;
        if (folderState.collapsed.has(id)) folderState.collapsed.delete(id);
        else folderState.collapsed.add(id);
        localStorage.setItem("vg-collapsed-folders", JSON.stringify([...folderState.collapsed]));
        renderFolderTree(root, folderState.tree);
        return;
      }
      if (create) {
        event.stopPropagation();
        await createFolder(create.dataset.folderAdd || null);
        return;
      }
      if (rename) {
        event.stopPropagation();
        await renameFolder(rename.dataset.folderRename);
        return;
      }
      if (del) {
        event.stopPropagation();
        await deleteFolder(del.dataset.folderDelete);
        return;
      }
      if (row) {
        const folderId = row.dataset.folderId || "";
        document.dispatchEvent(new CustomEvent("vault:folder-selected", { detail: { folderId } }));
        if (!document.querySelector("[data-notes-page]")) {
          location.href = folderId ? `/notes?folder=${encodeURIComponent(folderId)}` : "/notes";
        }
      }
    });
  }

  async function createFolder(parentId = null) {
    const name = prompt("Folder name");
    if (!name || !name.trim()) return;
    try {
      await apiFetch("/api/folders", {
        method: "POST",
        body: { name: name.trim(), parent_id: parentId || null }
      });
      toast("Folder created.", "success");
      await loadFolderTree();
      document.dispatchEvent(new CustomEvent("vault:folders-changed"));
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function renameFolder(folderId) {
    const name = prompt("New folder name");
    if (!name || !name.trim()) return;
    try {
      await apiFetch(`/api/folders/${encodeURIComponent(folderId)}`, {
        method: "PUT",
        body: { name: name.trim() }
      });
      toast("Folder renamed.", "success");
      await loadFolderTree();
      document.dispatchEvent(new CustomEvent("vault:folders-changed"));
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function deleteFolder(folderId) {
    const recursive = confirm("Delete this folder? Notes are preserved and moved to Unfiled. Press OK for recursive delete.");
    if (!recursive) return;
    try {
      await apiFetch(`/api/folders/${encodeURIComponent(folderId)}?recursive=true`, { method: "DELETE" });
      toast("Folder deleted.", "success");
      await loadFolderTree();
      document.dispatchEvent(new CustomEvent("vault:folders-changed"));
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function initCreateFolderButtons() {
    document.querySelectorAll("[data-create-folder]").forEach((button) => {
      button.addEventListener("click", () => createFolder(null));
    });
  }

  function flattenFolders(nodes, depth = 0, out = []) {
    nodes.forEach((node) => {
      out.push({ ...node, depth });
      flattenFolders(node.children || [], depth + 1, out);
    });
    return out;
  }

  function initUploads() {
    document.querySelectorAll("[data-upload-input], #note-upload").forEach((input) => {
      input.addEventListener("change", () => {
        const file = input.files && input.files[0];
        input.value = "";
        if (file) showUploadDialog(file);
      });
    });
  }

  async function showUploadDialog(file) {
    if (!file.name.toLowerCase().endsWith(".md")) {
      toast("Only .md Markdown files are accepted.", "error");
      return;
    }
    if (!folderState.tree.length) await loadFolderTree();
    const folders = flattenFolders(folderState.tree);
    const modal = document.createElement("div");
    modal.className = "modal-backdrop";
    modal.innerHTML = `
      <form class="modal-panel" data-upload-dialog>
        <h2>Upload Markdown</h2>
        <p class="muted">${escapeHtml(file.name)} · ${bytes(file.size)}</p>
        <label>Title
          <input class="input" name="title" value="${escapeHtml(file.name.replace(/\.md$/i, ""))}">
        </label>
        <label>Folder
          <select class="input" name="folder_id">
            <option value="">Unfiled</option>
            ${folders.map((folder) => `<option value="${escapeHtml(folder.id)}">${"&nbsp;".repeat(folder.depth * 3)}${escapeHtml(folder.name)}</option>`).join("")}
          </select>
        </label>
        <p class="status-line" data-upload-status>Ready to upload and index.</p>
        <div class="modal-actions">
          <button class="button button-secondary" type="button" data-modal-close>Cancel</button>
          <button class="button button-primary" type="submit">Upload</button>
        </div>
      </form>
    `;
    document.body.append(modal);
    modal.querySelector("[data-modal-close]").addEventListener("click", () => modal.remove());
    modal.addEventListener("click", (event) => {
      if (event.target === modal) modal.remove();
    });
    modal.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const status = form.querySelector("[data-upload-status]");
      const submit = form.querySelector("button[type='submit']");
      const formData = new FormData(form);
      formData.set("file", file);
      if (!formData.get("folder_id")) formData.delete("folder_id");
      submit.disabled = true;
      status.className = "status-line";
      status.textContent = "Uploading and indexing...";
      try {
        const result = await apiFetch("/api/notes/upload", { method: "POST", body: formData });
        status.className = result.ingested ? "status-line success" : "status-line";
        status.textContent = result.ingested
          ? `Indexed ${result.chunks_created} chunks.`
          : `Uploaded with indexing warnings: ${(result.errors || []).join(", ") || "No details"}`;
        toast("Markdown uploaded.", "success");
        document.dispatchEvent(new CustomEvent("vault:notes-changed"));
        setTimeout(() => { location.href = `/notes/${encodeURIComponent(result.note_id)}`; }, 500);
      } catch (err) {
        status.className = "status-line error";
        status.textContent = err.message;
        submit.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initAuthForms();
    initLogout();
    initFolderTree();
    initCreateFolderButtons();
    initUploads();
  });

  window.VG = {
    apiFetch,
    toast,
    escapeHtml,
    debounce,
    formatDate,
    loadFolderTree,
    showUploadDialog,
    flattenFolders
  };
})();
