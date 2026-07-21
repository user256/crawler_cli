/* Ticket 119: dependency-free UI adapter for Ticket 106 report_data.json.
 *
 * This module deliberately consumes the exported report envelope.  It does
 * not calculate embeddings, pairs, clusters, or risk labels in the browser.
 */

export const TYPE_FILTERS = [
  ["parent-child", "relation", true], ["sibling", "relation", true],
  ["same-section", "relation", true], ["cross-section", "relation", true],
  ["time-sequenced", "pair_class", true], ["thin", "thin", true],
  ["parameterised", "url_class", true], ["amp-variant", "amp", false],
  ["excluded", "excluded", false], ["off-topic", "off_topic", true],
];

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[c]);

export function adaptReportData(raw, run = {}) {
  if (!raw || !Array.isArray(raw.pages) || !Array.isArray(raw.pairs) || !Array.isArray(raw.clusters)) {
    throw new Error("Expected Ticket 106 report_data.json with pages, pairs, and clusters arrays.");
  }
  const pages = raw.pages.map((page, index) => ({ ...page, _index: index }));
  const byUrl = new Map(pages.map((page) => [page.url, page]));
  const clusterById = new Map(raw.clusters.map((cluster) => [String(cluster.id), cluster]));
  return {
    raw, pages, pairs: raw.pairs, clusters: raw.clusters, byUrl, clusterById,
    run: {
      id: run.id || raw.run_id || "fixture-run-2026-07-15",
      label: run.label || raw.run_label || "Static fixture run",
      completedAt: run.completedAt || raw.generated_at || "unknown time",
      artifact: run.artifact || "./report.html",
      artifactLabel: run.artifactLabel || "Export HTML (offline artifact)",
      source: run.source || "static fixture",
    },
  };
}

export function createViewerState(model) {
  return {
    search: "", risk: "all", activeTab: "clusters", selectedIndex: null,
    types: Object.fromEntries(TYPE_FILTERS.map(([id]) => [id, true])),
    selectedCluster: "all", selectedSection: "all",
    sort: { pages: ["max_similarity", -1], pairs: ["similarity", -1], clusters: ["size", -1] },
  };
}

/** Shared by map points, page rows, and cluster rows so selection cannot drift. */
export function selectPage(state, page) {
  state.selectedIndex = page ? page._index : null;
  return state.selectedIndex;
}

export function selectCluster(state, model, clusterId) {
  return selectPage(state, model.pages.find((page) => String(page.cluster_id) === String(clusterId)) || null);
}

function riskBucket(risk = "") {
  if (/duplicate|parent-child/.test(risk)) return "duplicate";
  if (/overlap|thin content|time-sequenced/.test(risk)) return "overlap";
  return "other";
}

function pageSection(page) {
  if (page.section) return String(page.section);
  try {
    const first = new URL(page.url).pathname.split("/").filter(Boolean)[0];
    return `/${first || "home"}`;
  } catch {
    return "/other";
  }
}

export function pageVisible(page, state) {
  const isAmp = page.variant_kind === "amp" || page.excluded === "amp-variant";
  if (isAmp ? !state.types["amp-variant"] : page.excluded && !state.types.excluded) return false;
  if (page.off_topic && !state.types["off-topic"]) return false;
  if (page.url_class === "parameterised" && !state.types.parameterised) return false;
  if (state.selectedCluster !== "all" && String(page.cluster_id) !== state.selectedCluster) return false;
  if (state.selectedSection !== "all" && pageSection(page) !== state.selectedSection) return false;
  if (state.search && !String(page.url).toLowerCase().includes(state.search.toLowerCase())) return false;
  return state.risk === "all" || (state.risk === "duplicate" ? riskBucket(page.risk) === "duplicate" : riskBucket(page.risk) !== "other");
}

export function pairVisible(pair, state, model) {
  if (pair.relation && state.types[pair.relation] === false) return false;
  if (pair.pair_class === "time-sequenced" && !state.types["time-sequenced"]) return false;
  if (pair.thin && !state.types.thin) return false;
  if (state.search && !`${pair.url_a} ${pair.url_b}`.toLowerCase().includes(state.search.toLowerCase())) return false;
  return [pair.url_a, pair.url_b].every((url) => !model.byUrl.has(url) || pageVisible(model.byUrl.get(url), state));
}

function countType([id, kind], model) {
  if (kind === "relation") return model.pairs.filter((pair) => pair.relation === id).length;
  if (kind === "pair_class") return model.pairs.filter((pair) => pair.pair_class === id).length;
  if (kind === "thin") return model.pairs.filter((pair) => pair.thin).length;
  if (kind === "url_class") return model.pages.filter((page) => page.url_class === "parameterised").length;
  if (kind === "amp") return model.pages.filter((page) => page.variant_kind === "amp" || page.excluded === "amp-variant").length;
  if (kind === "excluded") return model.pages.filter((page) => page.excluded).length;
  return model.pages.filter((page) => page.off_topic).length;
}

function sorted(rows, [key, direction]) {
  return [...rows].sort((a, b) => typeof a[key] === "number" && typeof b[key] === "number"
    ? (a[key] - b[key]) * direction : String(a[key] ?? "").localeCompare(String(b[key] ?? "")) * direction);
}

function table(root, columns, rows, tab, state, onSelect) {
  const header = columns.map((column) => `<th data-sort="${column}">${esc(column)}${state.sort[tab][0] === column ? (state.sort[tab][1] > 0 ? " ↑" : " ↓") : ""}</th>`).join("");
  const body = rows.map((row) => {
    const selected = tab === "pages" && row._index === state.selectedIndex ? " selected" : "";
    const attrs = tab === "pages" ? ` data-page="${row._index}"` : tab === "clusters" ? ` data-cluster="${esc(row.id)}"` : "";
    return `<tr class="${selected}"${attrs}>${columns.map((column) => `<td class="${column.includes("url") ? "mono" : ""}">${esc(row[column])}</td>`).join("")}</tr>`;
  }).join("") || `<tr><td colspan="${columns.length}" class="muted">No rows match the current filters.</td></tr>`;
  root.innerHTML = `<table class="data overlap-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
  root.querySelectorAll("[data-sort]").forEach((th) => th.onclick = () => {
    const key = th.dataset.sort; state.sort[tab] = [key, state.sort[tab][0] === key ? -state.sort[tab][1] : 1]; onSelect();
  });
  root.querySelectorAll("[data-page]").forEach((tr) => tr.onclick = () => { state.selectedIndex = Number(tr.dataset.page); onSelect(true); });
  root.querySelectorAll("[data-cluster]").forEach((tr) => tr.onclick = () => {
    const clusterId = tr.dataset.cluster;
    state.selectedIndex = onSelect.clusterFirst(clusterId); onSelect(true);
  });
}

export function mountIntentOverlapViewer(root, model) {
  const state = createViewerState(model);
  root.innerHTML = `<section class="intent-view" aria-label="Intent Overlap report">
    <header class="intent-header"><div><h2>Intent Overlap / Cluster Report</h2><p id="intent-run"></p></div><a id="intent-export" class="primary" target="_blank" rel="noopener">Export HTML</a></header>
    <div class="intent-summary" id="intent-summary"></div>
    <div class="intent-layout"><aside class="intent-filters"><label>URL search <input id="intent-search" type="search" placeholder="Filter URLs…"></label><label>Risk <select id="intent-risk"><option value="all">All risk</option><option value="duplicate">Duplicate risk</option><option value="overlap">Overlap / thin</option></select></label><label>Cluster <select id="intent-cluster"><option value="all">All clusters</option></select></label><label>Section <select id="intent-section"><option value="all">All sections</option></select></label><div class="intent-filter-actions"><button type="button" class="ghost" id="intent-clear-filters">Clear filters</button></div><h3>Page / match types</h3><div id="intent-types"></div></aside>
    <main class="intent-main"><div class="intent-map-wrap"><canvas id="intent-map" aria-label="Cluster map"></canvas><div id="intent-tooltip" class="intent-tooltip"></div><small>Wheel zoom · drag pan · click to pin · hover highlights cluster mates</small><button type="button" class="intent-reset-map" id="intent-reset-map">Reset view</button></div><section class="intent-tables"><nav id="intent-tabs" class="detail-tabs"><button data-tab="clusters" class="active">Clusters</button><button data-tab="pages">Pages</button><button data-tab="pairs">Pairs</button></nav><div id="intent-table" class="table-wrap"></div><div id="intent-detail" class="intent-detail">Select a map point or table row to inspect it.</div></section></main></div></section>`;
  root.querySelector("#intent-run").textContent = `Run ${model.run.id} · ${model.run.label} · ${model.run.completedAt} · ${model.run.source}${model.raw.layout_note ? ` · ${model.raw.layout_note}` : ""}`;
  const exportLink = root.querySelector("#intent-export"); exportLink.href = model.run.artifact; exportLink.textContent = model.run.artifactLabel;
  const canvas = root.querySelector("#intent-map"), tip = root.querySelector("#intent-tooltip"), ctx = canvas.getContext("2d");
  const mappable = model.pages.filter((page) => Array.isArray(page.coords) && page.coords.length >= 2);
  const xs = mappable.map((page) => page.coords[0]), ys = mappable.map((page) => page.coords[1]);
  const bounds = { minX: Math.min(...xs, 0), maxX: Math.max(...xs, 1), minY: Math.min(...ys, 0), maxY: Math.max(...ys, 1) };
  if (bounds.minX === bounds.maxX) bounds.maxX += 1; if (bounds.minY === bounds.maxY) bounds.maxY += 1;
  const view = { scale: 1, tx: 0, ty: 0, dragging: false, moved: false, x: 0, y: 0, hover: null };
  const color = (id) => `hsl(${[...String(id || "none")].reduce((n, c) => n * 31 + c.charCodeAt(0), 7) % 360} 62% 52%)`;
  // Keep zoom centred on the map rather than the canvas origin.  This means
  // the initial projection always fits, and wheel zoom can be anchored to the
  // pointer without sending the cluster off screen.
  const point = (page) => {
    const w = canvas.clientWidth, h = canvas.clientHeight, pad = 24;
    const baseX = pad + ((page.coords[0] - bounds.minX) / (bounds.maxX - bounds.minX)) * (w - pad * 2);
    const baseY = pad + (1 - (page.coords[1] - bounds.minY) / (bounds.maxY - bounds.minY)) * (h - pad * 2);
    return { x: w / 2 + (baseX - w / 2) * view.scale + view.tx, y: h / 2 + (baseY - h / 2) * view.scale + view.ty };
  };
  const focus = () => state.selectedIndex == null ? null : model.pages[state.selectedIndex];
  const draw = () => { const w = canvas.clientWidth, h = canvas.clientHeight; ctx.clearRect(0, 0, w, h); const selected = model.pages[state.selectedIndex] || model.pages[view.hover]; const edges = model.pairs.filter((pair) => selected && (pair.url_a === selected.url || pair.url_b === selected.url) && pairVisible(pair, state, model));
    edges.forEach((pair) => { const a = model.byUrl.get(pair.url_a), b = model.byUrl.get(pair.url_b); if (!a?.coords || !b?.coords) return; const pa = point(a), pb = point(b); ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.strokeStyle = "rgba(59,130,246,.5)"; ctx.stroke(); });
    mappable.filter((page) => pageVisible(page, state)).forEach((page) => { const p = point(page), mate = selected && selected.cluster_id && page.cluster_id === selected.cluster_id, isFocus = selected?.url === page.url; ctx.beginPath(); ctx.arc(p.x, p.y, isFocus ? 6 : mate ? 5 : 3, 0, Math.PI * 2); ctx.fillStyle = color(page.cluster_id); ctx.globalAlpha = selected && !mate && !isFocus ? .25 : .9; ctx.fill(); ctx.globalAlpha = 1; if (isFocus) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); } }); };
  // CSS owns the canvas box (100% of the grid row).  Only change the backing
  // buffer here: assigning a measured outer size back to the CSS box makes
  // the bordered map grow by a few pixels on every ResizeObserver callback.
  const resize = () => {
    const width = Math.max(1, canvas.clientWidth), height = Math.max(280, canvas.clientHeight), dpr = devicePixelRatio || 1;
    const bufferWidth = Math.round(width * dpr), bufferHeight = Math.round(height * dpr);
    if (canvas.width !== bufferWidth) canvas.width = bufferWidth;
    if (canvas.height !== bufferHeight) canvas.height = bufferHeight;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  };
  const resetView = () => { view.scale = 1; view.tx = 0; view.ty = 0; draw(); };
  const hit = (x, y) => mappable.filter((page) => pageVisible(page, state)).map((page) => [page, point(page)]).reduce((best, [page, p]) => Math.hypot(p.x - x, p.y - y) < best.distance ? { page, distance: Math.hypot(p.x - x, p.y - y) } : best, { page: null, distance: 10 }).page;
  const render = (focusSelected = false) => { const summary = model.raw.summary || {}; root.querySelector("#intent-summary").innerHTML = [["embedded", summary.embedded], ["pairs", summary.overlap_pairs], ["clusters", summary.clusters], ["duplicates", summary.duplicate_pages], ["thin", summary.thin_content_pages], ["threshold", summary.threshold]].map(([k, v]) => `<span>${k}: <strong>${esc(v ?? "—")}</strong></span>`).join("");
    root.querySelector("#intent-types").innerHTML = TYPE_FILTERS.map((filter) => `<label><input type="checkbox" data-type="${filter[0]}" ${state.types[filter[0]] ? "checked" : ""}> ${filter[0]} <b>${countType(filter, model)}</b></label>`).join("");
    root.querySelector("#intent-cluster").innerHTML = `<option value="all">All clusters</option>${model.clusters.map((cluster) => `<option value="${esc(cluster.id)}" ${state.selectedCluster === String(cluster.id) ? "selected" : ""}>${esc(cluster.label || cluster.id)} (${cluster.size})</option>`).join("")}`;
    const sections = [...new Set(model.pages.filter((page) => state.selectedCluster === "all" || String(page.cluster_id) === state.selectedCluster).map(pageSection))].sort();
    if (state.selectedSection !== "all" && !sections.includes(state.selectedSection)) state.selectedSection = "all";
    root.querySelector("#intent-section").innerHTML = `<option value="all">All sections</option>${sections.map((section) => `<option value="${esc(section)}" ${state.selectedSection === section ? "selected" : ""}>${esc(section)}</option>`).join("")}`;
    const rows = state.activeTab === "pages" ? sorted(model.pages.filter((page) => pageVisible(page, state)), state.sort.pages) : state.activeTab === "pairs" ? sorted(model.pairs.filter((pair) => pairVisible(pair, state, model)), state.sort.pairs) : sorted(model.clusters.filter((cluster) => state.selectedCluster === "all" || String(cluster.id) === state.selectedCluster), state.sort.clusters);
    const columns = state.activeTab === "pages" ? ["url", "cluster_id", "risk", "url_class", "word_count", "max_similarity"] : state.activeTab === "pairs" ? ["url_a", "url_b", "similarity", "relation", "pair_class", "thin"] : ["id", "label", "size", "relation", "thin", "suggested_canonical"];
    const rerender = (shouldFocus = false) => { render(shouldFocus); }; rerender.clusterFirst = (id) => { state.selectedCluster = String(id); state.selectedSection = "all"; return selectCluster(state, model, id); }; table(root.querySelector("#intent-table"), columns, rows, state.activeTab, state, rerender);
    root.querySelectorAll("[data-type]").forEach((input) => input.onchange = () => { state.types[input.dataset.type] = input.checked; render(); });
    const selected = focus(); root.querySelector("#intent-detail").innerHTML = selected ? `<strong>${esc(selected.url)}</strong><span>Cluster ${esc(selected.cluster_id || "unclustered")} · ${esc(selected.risk || "no risk")} · ${esc(selected.word_count ?? "—")} words · ${esc(selected.signature_words ?? "—")} signature words</span>` : "Select a map point or table row to inspect it.";
    if (focusSelected && selected?.coords) { const p = point(selected); view.tx += canvas.clientWidth / 2 - p.x; view.ty += canvas.clientHeight / 2 - p.y; } draw();
  };
  root.querySelector("#intent-search").oninput = (e) => { state.search = e.target.value; render(); }; root.querySelector("#intent-risk").onchange = (e) => { state.risk = e.target.value; render(); }; root.querySelector("#intent-cluster").onchange = (e) => { state.selectedCluster = e.target.value; state.selectedSection = "all"; render(); }; root.querySelector("#intent-section").onchange = (e) => { state.selectedSection = e.target.value; render(); }; root.querySelector("#intent-clear-filters").onclick = () => { state.search = ""; state.risk = "all"; state.selectedCluster = "all"; state.selectedSection = "all"; Object.keys(state.types).forEach((id) => { state.types[id] = true; }); root.querySelector("#intent-search").value = ""; root.querySelector("#intent-risk").value = "all"; render(); }; root.querySelector("#intent-tabs").onclick = (e) => { const button = e.target.closest("[data-tab]"); if (!button) return; state.activeTab = button.dataset.tab; root.querySelectorAll("[data-tab]").forEach((tab) => tab.classList.toggle("active", tab === button)); render(); }; root.querySelector("#intent-reset-map").onclick = resetView;
  canvas.onmousemove = (e) => { const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top; if (view.dragging) { const dx = x - view.x, dy = y - view.y; view.tx += dx; view.ty += dy; view.moved ||= Math.hypot(dx, dy) > 2; view.x = x; view.y = y; draw(); return; } const page = hit(x, y); view.hover = page?._index ?? null; if (page) { tip.hidden = false; tip.style.left = `${x + 12}px`; tip.style.top = `${y + 12}px`; tip.innerHTML = `<code>${esc(page.url)}</code><br>${esc(model.clusterById.get(String(page.cluster_id))?.label || page.cluster_id || "unclustered")} · ${esc(page.risk || "no risk")}`; } else tip.hidden = true; draw(); }; canvas.onmouseleave = () => { view.hover = null; tip.hidden = true; draw(); }; canvas.onmousedown = (e) => { view.dragging = true; view.moved = false; const r = canvas.getBoundingClientRect(); view.x = e.clientX - r.left; view.y = e.clientY - r.top; }; window.addEventListener("mouseup", () => { view.dragging = false; }); canvas.onclick = (e) => { if (view.moved) return; const r = canvas.getBoundingClientRect(), page = hit(e.clientX - r.left, e.clientY - r.top); if (page) { state.selectedIndex = page._index; render(true); } }; canvas.onwheel = (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, w = canvas.clientWidth, h = canvas.clientHeight, oldScale = view.scale; const localX = (x - w / 2 - view.tx) / oldScale, localY = (y - h / 2 - view.ty) / oldScale; const factor = e.deltaY < 0 ? 1.12 : .89; view.scale = Math.max(.45, Math.min(6, view.scale * factor)); view.tx = x - w / 2 - localX * view.scale; view.ty = y - h / 2 - localY * view.scale; draw(); };
  new ResizeObserver(resize).observe(canvas.parentElement); resize(); render();
  return { state, selectPage: (index) => { selectPage(state, model.pages[index]); render(true); } };
}
