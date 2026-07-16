/* crawler_gui — bind sample-data.json into the layout shell */

const state = {
  data: null,
  category: "internal",
  sidebar: "overview",
  detail: "url-details",
  selectedId: null,
  filter: "",
  historyFilter: "all",
  newCrawlType: "Spider",
  scheduleType: "Single URL",
  configContext: "crawl",
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 2400);
}

function setTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.dataset.theme = theme;
  $("#btn-theme").setAttribute("aria-pressed", String(isLight));
  $("#btn-theme").title = isLight ? "Switch to dark mode" : "Switch to light mode";
  $("#theme-label").textContent = isLight ? "Dark" : "Light";
  try {
    localStorage.setItem("crawler_gui-theme", theme);
  } catch {
    /* The prototype still works where storage is disabled. */
  }
}

function initialiseTheme() {
  let theme = "light";
  const requestedTheme = new URLSearchParams(window.location.search).get("theme");
  try {
    theme = requestedTheme || localStorage.getItem("crawler_gui-theme") || theme;
  } catch {
    /* Use the light default. */
  }
  setTheme(theme === "light" ? "light" : "dark");
}

function toneForStatus(code) {
  if (code >= 200 && code < 300) return "ok";
  if (code >= 300 && code < 400) return "warn";
  return "bad";
}

function toneForIndexability(v) {
  return v === "Indexable" ? "ok" : "warn";
}

function lenTone(n, softMin, softMax) {
  if (!n) return "warn";
  if (n < softMin || n > softMax) return "warn";
  return "ok";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function filteredPages() {
  const { data, category, filter } = state;
  let rows = data.pages;

  if (category === "external") {
    rows = rows.filter((p) => p.outlinks?.some((o) => o.external));
  } else if (category === "security") {
    rows = rows.filter((p) => !p.address.startsWith("https://") || p.statusCode >= 400);
  } else if (category !== "internal") {
    rows = rows.filter((p) => (p.categoryHints || []).includes(category));
  }

  const q = filter.trim().toLowerCase();
  if (q) {
    rows = rows.filter((p) =>
      [p.address, p.title, p.status, String(p.statusCode), p.contentType]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }
  return rows;
}

function columnsForCategory(cat) {
  const base = [
    { key: "row", label: "#" },
    { key: "address", label: "Address" },
  ];
  if (cat === "response-codes") {
    return [
      ...base,
      { key: "statusCode", label: "Status Code" },
      { key: "status", label: "Status" },
      { key: "redirectUrl", label: "Redirect URL" },
      { key: "contentType", label: "Content Type" },
      { key: "responseTimeMs", label: "Response Time" },
    ];
  }
  if (cat === "links") {
    return [
      ...base,
      { key: "internalInlinks", label: "Int. Inlinks" },
      { key: "externalInlinks", label: "Ext. Inlinks" },
      { key: "statusCode", label: "Status" },
    ];
  }
  if (cat === "page-titles") {
    return [
      ...base,
      { key: "title", label: "Title" },
      { key: "titleLength", label: "Length" },
      { key: "statusCode", label: "Status" },
    ];
  }
  if (cat === "meta-description") {
    return [
      ...base,
      { key: "metaDescription", label: "Meta Description" },
      { key: "metaDescriptionLength", label: "Length" },
      { key: "statusCode", label: "Status" },
    ];
  }
  if (cat === "h1") {
    return [
      ...base,
      { key: "h1", label: "H1" },
      { key: "h1Count", label: "H1 Count" },
      { key: "statusCode", label: "Status" },
    ];
  }
  return [
    ...base,
    { key: "contentType", label: "Content Type" },
    { key: "statusCode", label: "Status Code" },
    { key: "status", label: "Status" },
    { key: "indexability", label: "Indexability" },
    { key: "indexabilityStatus", label: "Indexability Status" },
    { key: "title", label: "Title" },
  ];
}

function cellValue(page, key, rowNum) {
  if (key === "row") return rowNum;
  if (key === "responseTimeMs") return page.responseTimeMs != null ? `${page.responseTimeMs} ms` : "";
  const v = page[key];
  return v == null || v === "" ? "—" : v;
}

function cellClass(page, key) {
  if (key === "statusCode" || key === "status") return `tone-${toneForStatus(page.statusCode)}`;
  if (key === "indexability") return `tone-${toneForIndexability(page.indexability)}`;
  if (key === "titleLength") return `tone-${lenTone(page.titleLength, 15, 60)}`;
  if (key === "metaDescriptionLength") return `tone-${lenTone(page.metaDescriptionLength, 70, 160)}`;
  if (key === "h1Count") return page.h1Count === 1 ? "tone-ok" : "tone-warn";
  if (key === "address") return "mono";
  return "";
}

function renderNav() {
  const { data } = state;
  $("#brand-name").textContent = data.meta.uiName;
  const nav = $("#nav-links");
  nav.innerHTML = data.nav
    .map(
      (n) =>
        `<button class="nav-link${n.id === "crawler" ? " active" : ""}" data-nav="${escapeHtml(n.id)}" ${
          n.enabled ? "" : "disabled"
        }>${escapeHtml(n.label)}</button>`
    )
    .join("");
}

function renderCrawlBar() {
  const c = state.data.crawl;
  $("#crawl-url").value = c.url;
  $("#crawl-mode").value = c.mode;
  const pct = c.progress.pct;
  $("#mini-progress-fill").style.width = `${pct}%`;
  $("#mini-progress-label").textContent = `${Math.round(pct)}%`;
}

function renderCategoryTabs() {
  const wrap = $("#category-tabs");
  wrap.innerHTML = state.data.categoryTabs
    .map(
      (t) =>
        `<button type="button" data-cat="${escapeHtml(t.id)}" class="${
          t.id === state.category ? "active" : ""
        }">${escapeHtml(t.label)}</button>`
    )
    .join("");
}

function renderTable() {
  const pages = filteredPages();
  const cols = columnsForCategory(state.category);
  $("#filter-total").textContent = `Filter Total: ${pages.length}`;

  const thead = `<tr>${cols.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("")}</tr>`;
  const tbody = pages
    .map((p, i) => {
      const selected = p.id === state.selectedId ? " selected" : "";
      const cells = cols
        .map((c) => {
          const cls = cellClass(p, c.key);
          return `<td class="${cls}">${escapeHtml(cellValue(p, c.key, i + 1))}</td>`;
        })
        .join("");
      return `<tr data-id="${p.id}" class="${selected}">${cells}</tr>`;
    })
    .join("");

  $("#grid-head").innerHTML = thead;
  $("#grid-body").innerHTML = tbody || `<tr><td colspan="${cols.length}" class="muted">No rows for this filter.</td></tr>`;
}

function renderSidebar() {
  const tabs = $("#sidebar-tabs");
  tabs.innerHTML = state.data.sidebarTabs
    .map(
      (t) =>
        `<button type="button" data-side="${escapeHtml(t.id)}" class="${
          t.id === state.sidebar ? "active" : ""
        }">${escapeHtml(t.label)}</button>`
    )
    .join("");

  const body = $("#sidebar-body");
  if (state.sidebar === "overview") {
    const ov = state.data.overview;
    body.innerHTML = [
      sectionHtml("Summary", ov.summary),
      sectionHtml("Response Codes", ov.responseCodes),
      sectionHtml("Content", ov.content),
    ].join("");
  } else if (state.sidebar === "issues") {
    body.innerHTML =
      `<div class="side-section"><h3>Issues</h3>` +
      state.data.issues
        .map(
          (iss) =>
            `<div class="issue-row"><span class="pill ${escapeHtml(iss.severity)}">${escapeHtml(
              iss.severity
            )}</span><span>${escapeHtml(iss.label)}</span><span class="count" style="margin-left:auto">${
              iss.count
            }</span></div>`
        )
        .join("") +
      `</div>`;
  } else if (state.sidebar === "structure") {
    const hosts = {};
    for (const p of state.data.pages) {
      try {
        const u = new URL(p.address);
        const key = u.pathname.split("/").filter(Boolean)[0] || "/";
        hosts[key] = (hosts[key] || 0) + 1;
      } catch {
        /* ignore */
      }
    }
    body.innerHTML =
      `<div class="side-section"><h3>Path segments</h3>` +
      Object.entries(hosts)
        .sort((a, b) => b[1] - a[1])
        .map(
          ([k, n]) =>
            `<div class="stat-row"><span>/${escapeHtml(k)}</span><span class="count">${n}</span></div>`
        )
        .join("") +
      `</div>`;
  } else {
    body.innerHTML = `<p class="muted">Live progress feed — prototype shows completed crawl only.</p>`;
  }
}

function sectionHtml(title, rows) {
  return (
    `<div class="side-section"><h3>${escapeHtml(title)}</h3>` +
    rows
      .map((r) => {
        const tone = r.tone ? ` tone-${r.tone}` : "";
        return `<div class="stat-row"><span class="${tone.trim()}">${escapeHtml(
          r.label
        )}</span><span><span class="count${tone}">${r.count}</span> <span class="pct">${r.pct}%</span></span></div>`;
      })
      .join("") +
    `</div>`
  );
}

function selectedPage() {
  return state.data.pages.find((p) => p.id === state.selectedId) || null;
}

function renderDetailTabs() {
  const wrap = $("#detail-tabs");
  wrap.innerHTML = state.data.detailTabs
    .map(
      (t) =>
        `<button type="button" data-detail="${escapeHtml(t.id)}" class="${
          t.id === state.detail ? "active" : ""
        }">${escapeHtml(t.label)}</button>`
    )
    .join("");
}

function renderDetail() {
  renderDetailTabs();
  const body = $("#detail-body");
  const page = selectedPage();
  if (!page) {
    body.innerHTML = `<div class="detail-empty">Select a URL in the grid to inspect details.</div>`;
    return;
  }

  if (state.detail === "url-details") {
    body.innerHTML = `
      <div class="detail-grid">
        <div>
          <h4>Technical</h4>
          ${kv("URL", page.address, "mono")}
          ${kv("Status Code", page.statusCode, `tone-${toneForStatus(page.statusCode)}`)}
          ${kv("Status", page.status, `tone-${toneForStatus(page.statusCode)}`)}
          ${kv("Content Type", page.contentType)}
          ${kv("Redirect URL", page.redirectUrl || "—")}
          ${kv("Response Time", `${page.responseTimeMs} ms`)}
          ${kv("Robots", page.robots)}
          ${kv("Canonical", page.canonical || "—", "mono")}
        </div>
        <div>
          <h4>On-page SEO</h4>
          ${kv("Page Title", page.title || "—")}
          ${kv("Title Length", `${page.titleLength} chars`, `tone-${lenTone(page.titleLength, 15, 60)}`)}
          ${kv("Meta Description", page.metaDescription || "—")}
          ${kv(
            "Meta Description Length",
            `${page.metaDescriptionLength} chars`,
            `tone-${lenTone(page.metaDescriptionLength, 70, 160)}`
          )}
          ${kv("H1", page.h1 || "—")}
          ${kv("H1 Count", page.h1Count, page.h1Count === 1 ? "tone-ok" : "tone-warn")}
          ${kv("Word Count", page.wordCount)}
        </div>
      </div>`;
  } else if (state.detail === "inlinks") {
    body.innerHTML = linkTable(
      ["Source URL", "Anchor Text", "Follow"],
      (page.inlinks || []).map((l) => [l.sourceUrl, l.anchorText, l.follow ? "True" : "False"])
    );
  } else if (state.detail === "outlinks") {
    body.innerHTML = linkTable(
      ["Target URL", "Anchor Text", "External"],
      (page.outlinks || []).map((l) => [l.targetUrl, l.anchorText, l.external ? "True" : "False"])
    );
  } else if (state.detail === "serp") {
    body.innerHTML = `
      <div class="serp-preview">
        <div class="url">${escapeHtml(page.address)}</div>
        <div class="title">${escapeHtml(page.title || page.address)}</div>
        <div class="desc">${escapeHtml(page.metaDescription || "No meta description.")}</div>
      </div>`;
  } else if (state.detail === "headers") {
    const entries = Object.entries(page.headers || {}).filter(([, v]) => v != null);
    body.innerHTML = linkTable(
      ["Header", "Value"],
      entries.map(([k, v]) => [k, String(v)])
    );
  } else if (state.detail === "structured-data") {
    const rows = (page.structuredData || []).map((s) => [s.type, s.name || s.headline || ""]);
    body.innerHTML = rows.length
      ? linkTable(["Type", "Name / Headline"], rows)
      : `<p class="muted">No structured data on this URL.</p>`;
  }
}

function kv(label, value, cls = "") {
  return `<div class="kv"><dt>${escapeHtml(label)}</dt><dd class="${cls}">${escapeHtml(
    value
  )}</dd></div>`;
}

function linkTable(headers, rows) {
  if (!rows.length) return `<p class="muted">None.</p>`;
  return `<div class="table-wrap"><table class="data"><thead><tr>${headers
    .map((h) => `<th>${escapeHtml(h)}</th>`)
    .join("")}</tr></thead><tbody>${rows
    .map(
      (r) =>
        `<tr>${r.map((c, i) => `<td class="${i === 0 ? "mono" : ""}">${escapeHtml(c)}</td>`).join("")}</tr>`
    )
    .join("")}</tbody></table></div>`;
}

function renderStatusbar() {
  const c = state.data.crawl;
  $("#status-label").textContent = c.statusLabel;
  $("#status-avg").textContent = `Average: ${c.speed.average} URL/s`;
  $("#status-cur").textContent = `Current: ${c.speed.current} URL/s`;
  const pct = c.progress.pct;
  $("#status-fill").style.width = `${pct}%`;
  $("#status-fill-label").textContent = `Completed ${c.progress.completed} of ${c.progress.total} (${pct.toFixed(
    2
  )}%) ${c.progress.remaining} Remaining`;
}

function renderHistoryModal() {
  const list = $("#history-list");
  let items = state.data.history;
  if (state.historyFilter !== "all") {
    items = items.filter((h) => h.status === state.historyFilter);
  }
  list.innerHTML = items
    .map(
      (h) => `
    <div class="history-card${h.viewing ? " viewing" : ""}">
      <div>
        <div>
          <span class="badge ${escapeHtml(h.status)}">${escapeHtml(h.status)}</span>
          ${h.viewing ? `<span class="badge viewing">Viewing</span>` : ""}
        </div>
        <strong>${escapeHtml(h.domain)}</strong>
        <div class="muted mono">${escapeHtml(h.url)}</div>
        <div class="muted">${escapeHtml(h.date)} · ${h.urls} URLs · ${h.htmlStored} HTML</div>
      </div>
    </div>`
    )
    .join("") || `<p class="muted">No crawls in this filter.</p>`;
}

function renderOptionsModal() {
  const cfg = state.data.configDefaults;
  const isSchedule = state.configContext === "schedule";
  $("#options-context").textContent = isSchedule ? "NEW SCHEDULE" : "CURRENT CRAWL";
  $("#config-notice").textContent = isSchedule
    ? "⚡ Changes apply to this scheduled crawl. They are saved when you create the schedule."
    : "⚡ Changes apply to the next crawl. Keep requests within the site’s published crawl policy.";
  $("#opt-max-pages").value = cfg.maxPages;
  $("#opt-concurrency").value = cfg.concurrency;
  $("#opt-delay").value = cfg.delay;
  $("#opt-backend").value = cfg.backend;
  $("#opt-user-agent").value = cfg.userAgent;
  $("#opt-robots").checked = cfg.respectRobots;
  $("#opt-js").checked = cfg.useJs;
  $("#opt-nofollow").checked = cfg.ignoreNoFollow;
  $("#opt-images").checked = cfg.crawlImages;
  $("#opt-concurrency-value").textContent = cfg.concurrency;
}

function renderScheduleModal() {
  const isList = state.scheduleType === "List of URLs";
  $("#schedule-target-label").textContent = isList ? "URL list location" : "Seed URL";
  $("#schedule-url").placeholder = isList ? "https://example.com/urls.txt" : "https://example.com";
  $$("[data-schedule-type]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.scheduleType === state.scheduleType);
  });
  const cfg = state.data.configDefaults;
  $("#schedule-options-summary").textContent = `${cfg.concurrency} req/s · ${cfg.respectRobots ? "robots respected" : "custom rules"}`;
}

function renderNewCrawlModal() {
  const isList = state.newCrawlType === "List";
  $("#new-crawl-url").value = isList ? "" : state.data.crawl.url;
  $("#new-crawl-target-label").textContent = isList ? "URL list location" : "Seed URL";
  $("#new-crawl-url").placeholder = isList ? "https://example.com/urls.txt" : "https://example.com";
  $("#new-crawl-hint").textContent = isList
    ? "Provide a hosted URL list. Each entry becomes a crawl target."
    : "Discovers pages by following internal links from this URL.";
  $$("[data-crawl-type]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.crawlType === state.newCrawlType);
  });
}

function openModal(id) {
  $(id).classList.add("open");
}

function closeModals() {
  $$(".modal-backdrop").forEach((m) => m.classList.remove("open"));
}

function bindEvents() {
  $("#nav-links").addEventListener("click", (e) => {
    const btn = e.target.closest('[data-nav="schedule"]');
    if (!btn || btn.disabled) return;
    renderScheduleModal();
    openModal("#modal-new-schedule");
  });

  $("#category-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cat]");
    if (!btn) return;
    state.category = btn.dataset.cat;
    renderCategoryTabs();
    renderTable();
  });

  $("#sidebar-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-side]");
    if (!btn) return;
    state.sidebar = btn.dataset.side;
    renderSidebar();
  });

  $("#detail-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-detail]");
    if (!btn) return;
    state.detail = btn.dataset.detail;
    renderDetail();
  });

  $("#grid-body").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    state.selectedId = Number(tr.dataset.id);
    renderTable();
    renderDetail();
  });

  $("#grid-filter").addEventListener("input", (e) => {
    state.filter = e.target.value;
    renderTable();
  });

  $("#btn-history").addEventListener("click", () => {
    renderHistoryModal();
    openModal("#modal-history");
  });

  $("#btn-options").addEventListener("click", () => {
    state.configContext = "crawl";
    renderOptionsModal();
    openModal("#modal-options");
  });

  $("#btn-new-crawl").addEventListener("click", () => {
    renderNewCrawlModal();
    openModal("#modal-new-crawl");
  });

  $("#btn-new-schedule").addEventListener("click", () => {
    renderScheduleModal();
    openModal("#modal-new-schedule");
  });

  $("#btn-theme").addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });

  $("#modal-new-crawl").addEventListener("click", (e) => {
    const type = e.target.closest("[data-crawl-type]");
    if (!type) return;
    state.newCrawlType = type.dataset.crawlType;
    renderNewCrawlModal();
  });

  $("#modal-new-schedule").addEventListener("click", (e) => {
    const type = e.target.closest("[data-schedule-type]");
    if (!type) return;
    state.scheduleType = type.dataset.scheduleType;
    renderScheduleModal();
  });

  $("#btn-new-crawl-options").addEventListener("click", () => {
    closeModals();
    state.configContext = "crawl";
    renderOptionsModal();
    openModal("#modal-options");
  });

  $("#btn-schedule-options").addEventListener("click", () => {
    closeModals();
    state.configContext = "schedule";
    renderOptionsModal();
    openModal("#modal-options");
  });

  $("#btn-start-crawl").addEventListener("click", () => {
    const url = $("#new-crawl-url").value.trim();
    if (!url) {
      toast("Add a crawl target to continue");
      $("#new-crawl-url").focus();
      return;
    }
    state.data.crawl.url = url;
    state.data.crawl.mode = state.newCrawlType;
    state.data.crawl.statusLabel = `${state.newCrawlType} Mode: Ready`;
    closeModals();
    renderCrawlBar();
    renderStatusbar();
    toast("Prototype: crawl is ready to submit to crawler_api");
  });

  $("#btn-create-schedule").addEventListener("click", () => {
    const url = $("#schedule-url").value.trim();
    const day = Number($("#schedule-day").value);
    if (!url) {
      toast("Add a crawl target to create the schedule");
      $("#schedule-url").focus();
      return;
    }
    if (!Number.isInteger(day) || day < 1 || day > 28) {
      toast("Choose a day of the month from 1 to 28");
      $("#schedule-day").focus();
      return;
    }
    const name = $("#schedule-name").value.trim() || "Untitled monthly crawl";
    const time = $("#schedule-time").value || "09:00";
    const timezone = $("#schedule-timezone").value.trim() || "Europe/London";
    closeModals();
    toast(`${name} scheduled monthly on day ${day} at ${time} (${timezone})`);
  });

  $("#btn-delete").addEventListener("click", () => {
    toast("Prototype: would call delete-crawl / API drop");
  });

  $$("[data-close]").forEach((el) => el.addEventListener("click", closeModals));

  $("#history-filters").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-hfilter]");
    if (!btn) return;
    state.historyFilter = btn.dataset.hfilter;
    $$("#history-filters button").forEach((b) => b.classList.toggle("active", b === btn));
    renderHistoryModal();
  });

  $("#btn-save-options").addEventListener("click", () => {
    state.data.configDefaults = {
      maxPages: Number($("#opt-max-pages").value),
      concurrency: Number($("#opt-concurrency").value),
      delay: Number($("#opt-delay").value),
      backend: $("#opt-backend").value,
      respectRobots: $("#opt-robots").checked,
      useJs: $("#opt-js").checked,
      ignoreNoFollow: $("#opt-nofollow").checked,
      crawlImages: $("#opt-images").checked,
      userAgent: $("#opt-user-agent").value,
    };
    closeModals();
    toast(state.configContext === "schedule" ? "Scheduled crawl options saved" : "Configuration updated in local fixture state only");
  });

  $("#opt-concurrency").addEventListener("input", (e) => {
    $("#opt-concurrency-value").textContent = e.target.value;
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModals();
  });
}

function renderAll() {
  renderNav();
  renderCrawlBar();
  renderCategoryTabs();
  renderTable();
  renderSidebar();
  renderDetail();
  renderStatusbar();
}

async function main() {
  try {
    const res = await fetch("./sample-data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    state.data = await res.json();
    initialiseTheme();
    state.selectedId = state.data.pages[0]?.id ?? null;
    bindEvents();
    renderAll();
  } catch (err) {
    document.body.innerHTML = `<pre style="padding:2rem;color:#f87171">Failed to load sample-data.json.
Serve this folder over HTTP, e.g.:
  python3 -m http.server 8765
${escapeHtml(err.message)}</pre>`;
  }
}

main();
