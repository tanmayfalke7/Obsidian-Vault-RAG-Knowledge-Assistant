/* KnowledgeBase AI — minimal vanilla JS helpers */

// ── Dropzone ────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  const dropzone = document.querySelector('.dropzone');
  const fileInput = document.getElementById('file-input');

  if (dropzone && fileInput) {
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        fileInput.files = files;
        updateDropzoneLabel(files[0].name);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) updateDropzoneLabel(fileInput.files[0].name);
    });

    function updateDropzoneLabel(name) {
      const title = dropzone.querySelector('.dropzone-title');
      if (title) title.textContent = name;
    }
  }
});

// ── Auto-expand textarea ────────────────────────────────────────────────────
document.addEventListener('input', function (e) {
  if (e.target.classList.contains('chat-input')) {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px';
  }
});

// ── Chat: submit on Enter (Shift+Enter = newline) ───────────────────────────
document.addEventListener('keydown', function (e) {
  if (e.target.classList.contains('chat-input') && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const form = e.target.closest('form');
    if (form) {
      // Use HTMX submit if available
      if (window.htmx) htmx.trigger(form, 'submit');
      else form.submit();
    }
  }
});

// ── HTMX: scroll chat to bottom after new answer ───────────────────────────
document.body.addEventListener('htmx:afterSettle', function (e) {
  const chatMsgs = document.querySelector('.chat-messages');
  if (chatMsgs) chatMsgs.scrollTop = chatMsgs.scrollHeight;

  // Clear chat input after submit
  const chatInput = document.querySelector('.chat-input');
  if (chatInput && e.detail.requestConfig &&
      e.detail.requestConfig.path === '/chat/ask') {
    chatInput.value = '';
    chatInput.style.height = 'auto';
  }
});

// ── HTMX: show loading spinner on chat submit ───────────────────────────────
document.body.addEventListener('htmx:beforeRequest', function (e) {
  if (e.detail.requestConfig.path === '/chat/ask') {
    const btn = document.getElementById('chat-submit-btn');
    if (btn) btn.disabled = true;
  }
});

document.body.addEventListener('htmx:afterRequest', function (e) {
  if (e.detail.requestConfig.path === '/chat/ask') {
    const btn = document.getElementById('chat-submit-btn');
    if (btn) btn.disabled = false;
  }
});

// ── Delete confirmation ─────────────────────────────────────────────────────
document.addEventListener('click', function (e) {
  const btn = e.target.closest('[data-confirm]');
  if (btn) {
    const msg = btn.dataset.confirm || 'Are you sure?';
    if (!confirm(msg)) e.preventDefault();
  }
});

// ── Inline folder rename ────────────────────────────────────────────────────
document.addEventListener('dblclick', function (e) {
  const nameEl = e.target.closest('.folder-name-editable');
  if (!nameEl) return;
  const current = nameEl.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.value = current;
  input.className = 'form-input';
  input.style.cssText = 'width:100%;padding:.25rem .5rem;font-size:inherit';
  nameEl.replaceWith(input);
  input.focus(); input.select();
  function commit() {
    const newName = input.value.trim() || current;
    const span = document.createElement('span');
    span.className = 'folder-name-editable folder-name';
    span.textContent = newName;
    input.replaceWith(span);
    // Submit rename via hidden form if present
    const folderId = span.closest('[data-folder-id]')?.dataset.folderId;
    if (folderId && newName !== current) {
      fetch(`/folders/${folderId}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded',
                   'HX-Request': 'true' },
        body: `name=${encodeURIComponent(newName)}`,
      });
    }
  }
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { input.value = current; input.blur(); }
  });
});

// ── Flash messages auto-dismiss ─────────────────────────────────────────────
document.querySelectorAll('.alert[data-auto-dismiss]').forEach(el => {
  setTimeout(() => el.style.opacity = '0', 4000);
  setTimeout(() => el.remove(), 4500);
});
