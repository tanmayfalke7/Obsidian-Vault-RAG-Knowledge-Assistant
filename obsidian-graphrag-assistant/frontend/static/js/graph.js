(() => {
  const canvas = document.querySelector("#graph-canvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const select = document.querySelector("#graph-note-select");
  const reset = document.querySelector("#graph-reset");
  const physicsBtn = document.querySelector("#graph-physics");
  const search = document.querySelector("#graph-node-search");
  const inspector = document.querySelector("#graph-inspector");
  const zoomIn = document.querySelector("#zoom-in");
  const zoomOut = document.querySelector("#zoom-out");

  const state = {
    nodes: [],
    edges: [],
    selected: null,
    hovered: null,
    dragging: null,
    zoom: 1,
    offsetX: 0,
    offsetY: 0,
    physics: true,
    filter: "",
    animation: null
  };

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function seedGraph(data) {
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const count = Math.max(1, data.nodes.length);
    state.nodes = data.nodes.map((node, index) => {
      const angle = (index / count) * Math.PI * 2;
      const radius = node.is_root ? 0 : 120 + (index % 4) * 35;
      return {
        ...node,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        r: node.type === "note" ? 20 : 15
      };
    });
    state.edges = data.edges || [];
    state.selected = null;
    draw();
    startAnimation();
  }

  async function loadNoteGraph(noteId) {
    if (!noteId) {
      state.nodes = [];
      state.edges = [];
      inspector.innerHTML = '<p class="muted">Choose a note graph to begin.</p>';
      draw();
      return;
    }
    inspector.innerHTML = '<p class="status-line">Loading graph...</p>';
    try {
      const data = await VG.apiFetch(`/api/graph/note/${encodeURIComponent(noteId)}?max_nodes=100`);
      seedGraph(data);
      inspector.innerHTML = '<p class="muted">Select a node on the canvas.</p>';
    } catch (err) {
      inspector.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    }
  }

  async function expandConcept(node) {
    inspector.innerHTML = '<p class="status-line">Expanding concept...</p>';
    try {
      const data = await VG.apiFetch(`/api/graph/concept/${encodeURIComponent(node.id)}?depth=2&max_nodes=120`);
      seedGraph(data);
      const next = state.nodes.find((item) => item.id === node.id);
      if (next) selectNode(next);
    } catch (err) {
      inspector.innerHTML = `<p class="status-line error">${VG.escapeHtml(err.message)}</p>`;
    }
  }

  function startAnimation() {
    cancelAnimationFrame(state.animation);
    const tick = () => {
      if (state.physics) stepPhysics();
      draw();
      state.animation = requestAnimationFrame(tick);
    };
    tick();
  }

  function stepPhysics() {
    const rect = canvas.getBoundingClientRect();
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const byId = new Map(state.nodes.map((node) => [node.id, node]));

    state.nodes.forEach((a, index) => {
      for (let i = index + 1; i < state.nodes.length; i += 1) {
        const b = state.nodes[i];
        const dx = a.x - b.x || 0.01;
        const dy = a.y - b.y || 0.01;
        const distSq = Math.max(dx * dx + dy * dy, 80);
        const force = 2600 / distSq;
        const dist = Math.sqrt(distSq);
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force;
        b.vy -= (dy / dist) * force;
      }
    });

    state.edges.forEach((edge) => {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const force = (dist - 150) * 0.006;
      a.vx += (dx / dist) * force;
      a.vy += (dy / dist) * force;
      b.vx -= (dx / dist) * force;
      b.vy -= (dy / dist) * force;
    });

    state.nodes.forEach((node) => {
      if (node === state.dragging) return;
      node.vx += (centerX - node.x) * 0.002;
      node.vy += (centerY - node.y) * 0.002;
      node.vx *= 0.86;
      node.vy *= 0.86;
      node.x += node.vx;
      node.y += node.vy;
    });
  }

  function draw() {
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.save();
    ctx.translate(state.offsetX, state.offsetY);
    ctx.scale(state.zoom, state.zoom);

    const byId = new Map(state.nodes.map((node) => [node.id, node]));
    state.edges.forEach((edge) => {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b) return;
      ctx.strokeStyle = "#c9c9c2";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      ctx.fillStyle = "#6b7268";
      ctx.font = "11px sans-serif";
      ctx.fillText(edge.type || "RELATES", mx + 4, my - 4);
    });

    state.nodes.forEach((node) => {
      const hidden = state.filter && !node.label.toLowerCase().includes(state.filter);
      ctx.globalAlpha = hidden ? 0.18 : 1;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fillStyle = colorFor(node);
      ctx.fill();
      ctx.lineWidth = node === state.selected ? 4 : 1.5;
      ctx.strokeStyle = node === state.selected ? "#d48806" : "#ffffff";
      ctx.stroke();
      ctx.fillStyle = "#1c1f1d";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(trimLabel(node.label), node.x, node.y + node.r + 15);
      ctx.globalAlpha = 1;
    });
    ctx.restore();

    if (!state.nodes.length) {
      ctx.fillStyle = "#6b7268";
      ctx.font = "15px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Choose a note to load its graph.", rect.width / 2, rect.height / 2);
    }
  }

  function colorFor(node) {
    if (node.type === "note") return "#2c382f";
    if (node.type === "chunk") return "#9aa098";
    return "#d48806";
  }

  function trimLabel(label) {
    return label.length > 22 ? `${label.slice(0, 21)}...` : label;
  }

  function pointerPosition(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - state.offsetX) / state.zoom,
      y: (event.clientY - rect.top - state.offsetY) / state.zoom
    };
  }

  function hitTest(event) {
    const pos = pointerPosition(event);
    return [...state.nodes].reverse().find((node) => {
      const dx = pos.x - node.x;
      const dy = pos.y - node.y;
      return Math.sqrt(dx * dx + dy * dy) <= node.r + 6;
    });
  }

  async function selectNode(node) {
    state.selected = node;
    draw();
    const actions = node.type === "note"
      ? `<a class="button button-secondary" href="/notes/${VG.escapeHtml(String(node.id).split(":").pop())}">Open Note</a>`
      : `<button class="button button-secondary" type="button" data-expand-concept="${VG.escapeHtml(node.id)}">Expand Neighbors</button>`;
    inspector.innerHTML = `
      <dl class="meta-list">
        <div><dt>Label</dt><dd>${VG.escapeHtml(node.label)}</dd></div>
        <div><dt>Type</dt><dd>${VG.escapeHtml(node.type)}</dd></div>
        <div><dt>ID</dt><dd>${VG.escapeHtml(node.id)}</dd></div>
      </dl>
      <div class="panel-toolbar">${actions}</div>
    `;
  }

  canvas.addEventListener("mousedown", (event) => {
    const node = hitTest(event);
    if (node) {
      state.dragging = node;
      state.selected = node;
      selectNode(node);
    }
  });
  canvas.addEventListener("mousemove", (event) => {
    const node = hitTest(event);
    canvas.style.cursor = node ? "grab" : "default";
    if (state.dragging) {
      const pos = pointerPosition(event);
      state.dragging.x = pos.x;
      state.dragging.y = pos.y;
      state.dragging.vx = 0;
      state.dragging.vy = 0;
      draw();
    }
  });
  window.addEventListener("mouseup", () => {
    state.dragging = null;
  });
  canvas.addEventListener("dblclick", (event) => {
    const node = hitTest(event);
    if (node && node.type !== "note") expandConcept(node);
  });

  select?.addEventListener("change", () => loadNoteGraph(select.value));
  reset?.addEventListener("click", () => {
    state.zoom = 1;
    state.offsetX = 0;
    state.offsetY = 0;
    if (select.value) loadNoteGraph(select.value);
  });
  physicsBtn?.addEventListener("click", () => {
    state.physics = !state.physics;
    physicsBtn.textContent = state.physics ? "Physics On" : "Physics Off";
    physicsBtn.setAttribute("aria-pressed", String(state.physics));
  });
  search?.addEventListener("input", () => {
    state.filter = search.value.trim().toLowerCase();
    draw();
  });
  zoomIn?.addEventListener("click", () => {
    state.zoom = Math.min(2.2, state.zoom + 0.15);
    draw();
  });
  zoomOut?.addEventListener("click", () => {
    state.zoom = Math.max(0.45, state.zoom - 0.15);
    draw();
  });
  inspector.addEventListener("click", (event) => {
    const button = event.target.closest("[data-expand-concept]");
    if (!button) return;
    const node = state.nodes.find((item) => item.id === button.dataset.expandConcept);
    if (node) expandConcept(node);
  });

  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();
  startAnimation();
})();
