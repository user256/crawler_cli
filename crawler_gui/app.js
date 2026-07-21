/* crawler_gui — bind sample-data.json into the layout shell */
import { adaptReportData, mountIntentOverlapViewer } from "./intent-overlap.mjs";
import { REPORT_DATA } from "./intent-report-fixture.mjs";
import { REPORT_DATA as THOMPSONS_REPORT_DATA } from "./thompsons-intent-report.mjs";

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
  view: "crawler",
  intentViewer: null,
  intentDataset: "fixture",
  live: false,
  pageLimit: null,
  crawlJobId: null,
  chromeProfiles: [],
};

const INTENT_ONLY_DATA = {
  meta: { uiName: "crawler_gui" },
  nav: [{ id: "intent-overlap", label: "Intent Overlap", enabled: true }],
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
        `<button class="nav-link${n.id === state.view ? " active" : ""}" data-nav="${escapeHtml(n.id)}" ${
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
  renderRunSelector();
}

function runOptionLabel(run) {
  // "legacy" is crawler_cli's migration run holding pre-run-scoped current
  // state, not a crawl someone started — say so instead of showing "—".
  const name = run.id === "legacy" ? "legacy (migrated current state)" : run.domain || run.url || run.id;
  const bits = [name, `${run.urls} URLs`];
  if (run.date) bits.push(run.date);
  if (run.status && run.id !== "legacy") bits.push(run.status);
  return bits.join(" · ");
}

function renderRunSelector() {
  const select = $("#run-selector");
  const runs = state.data.history || [];
  // The fixture prototype has no bridge to switch against, so the selector is
  // live-only; history cards still render in both modes.
  if (!state.live || runs.length === 0) {
    select.hidden = true;
    return;
  }
  select.hidden = false;
  select.innerHTML = runs
    .map(
      (run) =>
        `<option value="${escapeHtml(run.id)}"${run.id === state.data.crawl.id ? " selected" : ""}>${escapeHtml(
          runOptionLabel(run)
        )}</option>`
    )
    .join("");
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

function renderLiveNote() {
  const note = $("#live-note");
  const more = $("#btn-load-more");
  const live = state.data.live;
  if (!state.live || !live) {
    note.hidden = true;
    more.hidden = true;
    return;
  }
  const loaded = state.data.pages.length;
  const parts = [];
  // A partial view must say so — never let a capped window read as the whole run.
  if (live.hasMore) parts.push(`Showing ${loaded} of ${live.totalPages} URLs`);
  else if (live.totalPages) parts.push(`All ${live.totalPages} URLs loaded`);
  if (live.runScoped === false) parts.push("current state — not run-scoped");
  note.textContent = parts.join(" · ");
  note.hidden = parts.length === 0;
  more.hidden = !live.hasMore;
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
    <div class="history-card${h.viewing ? " viewing" : ""}" data-run="${escapeHtml(h.id)}">
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

function syncChromeProfileControls() {
  const select = $("#opt-chrome-profile");
  const backend = $("#opt-backend").value;
  const selected = state.chromeProfiles.find((profile) => profile.id === select.value);
  const obscura = $("#opt-backend option[value='obscura']");
  if (obscura) obscura.disabled = Boolean(selected);
  if (selected && backend === "obscura") {
    $("#opt-backend").value = "playwright";
  }
  const hint = $("#opt-chrome-profile-hint");
  if (!selected) {
    hint.textContent = state.live
      ? "Choose a discovered profile to launch headed Chrome. Close Chrome before starting; dedicated user-data directories are recommended."
      : "Available in live mode. Profile metadata is read locally; cookies are never returned.";
  } else if (selected.locked) {
    hint.textContent = "Chrome is using this profile. Close Chrome first, then start the crawl.";
  } else if (selected.warning) {
    hint.textContent = selected.warning;
  } else {
    hint.textContent = `${selected.name} · ${selected.profileDirectory} · persistent Playwright profile`;
  }
}

async function loadChromeProfiles() {
  const select = $("#opt-chrome-profile");
  if (!state.live) {
    select.disabled = true;
    select.innerHTML = "<option value=\"\">No persistent profile</option>";
    state.chromeProfiles = [];
    syncChromeProfileControls();
    return;
  }
  try {
    const res = await fetch(new URL("./api/live/chrome-profiles", window.location.href), { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const body = await res.json();
    state.chromeProfiles = Array.isArray(body.profiles) ? body.profiles : [];
    const selectedId = state.data.configDefaults.chromeProfileId || "";
    select.innerHTML = "<option value=\"\">No persistent profile</option>";
    state.chromeProfiles.forEach((profile) => {
      const option = document.createElement("option");
      option.value = profile.id;
      option.textContent = `${profile.name}${profile.email ? ` · ${profile.email}` : ""}${profile.lastUsed ? " · last used" : ""}`;
      select.appendChild(option);
    });
    select.value = state.chromeProfiles.some((profile) => profile.id === selectedId) ? selectedId : "";
    select.disabled = state.chromeProfiles.length === 0;
    if (!state.chromeProfiles.length) {
      $("#opt-chrome-profile-hint").textContent = "No Chrome profiles were discovered. Create a profile or use a dedicated Playwright user-data directory.";
    }
  } catch (err) {
    state.chromeProfiles = [];
    select.disabled = true;
    select.innerHTML = "<option value=\"\">Profile discovery unavailable</option>";
    $("#opt-chrome-profile-hint").textContent = `Could not inspect local Chrome profiles: ${err.message}`;
  }
  syncChromeProfileControls();
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
  loadChromeProfiles();
  syncChromeProfileControls();
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
    const btn = e.target.closest("[data-nav]");
    if (!btn || btn.disabled) return;
    if (btn.dataset.nav === "schedule") {
      renderScheduleModal();
      openModal("#modal-new-schedule");
    } else if (btn.dataset.nav === "intent-overlap") {
      showIntentOverlap();
    } else if (btn.dataset.nav === "crawler") {
      showCrawler();
    }
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

  $("#btn-load-more").addEventListener("click", loadMore);

  $("#run-selector").addEventListener("change", (e) => switchRun(e.target.value));

  $("#history-list").addEventListener("click", (e) => {
    const card = e.target.closest("[data-run]");
    if (!card || !state.live) return;
    closeModals();
    switchRun(card.dataset.run);
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
    if (state.live) {
      startLiveCrawl(url);
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
    toast(state.live ? "Live GUI is read-only; delete remains a crawler_api action." : "Prototype: would call delete-crawl / API drop");
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
    const selectedProfile = state.chromeProfiles.find((profile) => profile.id === $("#opt-chrome-profile").value);
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
      chromeProfileId: selectedProfile?.id || "",
      browserChannel: selectedProfile?.browser === "chromium" ? "chromium" : selectedProfile ? "chrome" : "",
      userDataDir: selectedProfile?.userDataDir || "",
      profileDirectory: selectedProfile?.profileDirectory || "",
    };
    closeModals();
    toast(state.configContext === "schedule" ? "Scheduled crawl options saved" : "Configuration updated in local fixture state only");
  });

  $("#opt-concurrency").addEventListener("input", (e) => {
    $("#opt-concurrency-value").textContent = e.target.value;
  });

  $("#opt-chrome-profile").addEventListener("change", () => {
    syncChromeProfileControls();
  });
  $("#opt-backend").addEventListener("change", () => {
    syncChromeProfileControls();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModals();
  });
}

function showCrawler() {
  state.view = "crawler";
  $(".stage").hidden = false;
  $("#category-tabs").hidden = false;
  $("#intent-overlap-root").hidden = true;
  renderNav();
}

function showIntentOverlap() {
  state.view = "intent-overlap";
  $(".stage").hidden = true;
  $("#category-tabs").hidden = true;
  const root = $("#intent-overlap-root");
  root.hidden = false;
  if (!state.intentViewer) {
    const isThompsons = state.intentDataset === "thompsons";
    const report = isThompsons ? THOMPSONS_REPORT_DATA : REPORT_DATA;
    // Static fixture today; replace only this adapter input with the future
    // deterministic GET /crawls/{crawl_id}/runs/{run_id}/intent-report endpoint.
    state.intentViewer = mountIntentOverlapViewer(root, adaptReportData(report, {
      id: isThompsons ? "thompsons-scotland-20260715" : "crawl_whiskipedia_demo/run_2026-07-15T14:08:04Z",
      label: isThompsons ? "Thompsons Scotland completed crawl" : "Whiskipedia completed crawl snapshot",
      completedAt: isThompsons ? "2026-07-15T11:46:25Z" : "2026-07-15T14:08:04Z",
      artifact: isThompsons ? "./thompsons-intent-report.mjs" : "./report.html",
      artifactLabel: isThompsons ? "View report data" : "Export HTML (offline artifact)",
      source: isThompsons ? "exported crawl CSV reports; deterministic map layout" : "static Ticket 106 fixture (no API request)",
    }));
    if (isThompsons) $(".user-chip").textContent = "Thompsons Scotland · crawl export";
  }
  renderNav();
}

async function fetchSnapshot({ run, offset = 0, limit = state.pageLimit } = {}) {
  const endpoint = new URL("./api/live/snapshot", window.location.href);
  if (run) endpoint.searchParams.set("run", run);
  if (offset) endpoint.searchParams.set("offset", String(offset));
  if (limit) endpoint.searchParams.set("limit", String(limit));
  const res = await fetch(endpoint, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function liveChipLabel() {
  return state.data.crawl.id ? `live Postgres · ${state.data.crawl.id}` : "live Postgres · no crawls yet";
}

async function startLiveCrawl(url) {
  const btn = $("#btn-start-crawl");
  btn.disabled = true;
  btn.textContent = "Starting…";
  try {
    const cfg = state.data.configDefaults || {};
    const res = await fetch(new URL("./api/live/crawls", window.location.href), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        mode: state.newCrawlType,
        name: $("#new-crawl-name").value.trim(),
        maxPages: cfg.maxPages,
        concurrency: cfg.concurrency,
        backend: cfg.useJs ? "playwright" : cfg.backend,
        userAgent: cfg.userAgent,
        respectRobots: cfg.respectRobots,
        browserChannel: cfg.browserChannel,
        userDataDir: cfg.userDataDir,
        profileDirectory: cfg.profileDirectory,
      }),
    });
    // Read the body once: bridge errors are plain text, successes are JSON.
    const raw = await res.text();
    let body = null;
    try {
      body = JSON.parse(raw);
    } catch {
      /* A refusal (409 already running, 400 bad target) explains itself in text. */
    }
    if (!res.ok) throw new Error(raw || `${res.status} ${res.statusText}`);
    closeModals();
    state.crawlJobId = body.jobId;
    toast(`Crawl started — run ${body.runId}`);
    pollCrawlJob(body.jobId);
  } catch (err) {
    toast(`Could not start crawl: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Start crawl";
  }
}

async function pollCrawlJob(jobId) {
  clearTimeout(pollCrawlJob._t);
  let job = null;
  try {
    const res = await fetch(new URL(`./api/live/crawls/${jobId}`, window.location.href), { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    job = await res.json();
  } catch (err) {
    toast(`Lost track of the crawl job: ${err.message}`);
    return;
  }
  $("#status-label").textContent = `Crawl ${job.state} · run ${job.runId}`;
  if (job.state === "running") {
    pollCrawlJob._t = setTimeout(() => pollCrawlJob(jobId), 2000);
    return;
  }
  if (job.state === "failed") {
    // Surface the real reason instead of letting the run vanish silently.
    const tail = (job.log || []).slice(-3).join(" | ") || `exit code ${job.exitCode}`;
    toast(`Crawl failed: ${tail}`);
  } else {
    toast(`Crawl finished — loading run ${job.runId}`);
  }
  await refreshRuns(job.runId);
}

async function refreshRuns(preferRunId) {
  try {
    const res = await fetch(new URL("./api/live/runs", window.location.href), { cache: "no-store" });
    if (!res.ok) return;
    const { runs } = await res.json();
    const target = runs.find((r) => r.id === preferRunId);
    if (target) {
      // The new run exists now, so show it without restarting the bridge.
      state.data.history = runs;
      await switchRun(preferRunId);
    } else {
      state.data.history = runs.map((r) => ({ ...r, viewing: r.id === state.data.crawl.id }));
      renderRunSelector();
    }
  } catch {
    /* Leave the current view intact; the selector still shows known runs. */
  }
}

async function switchRun(runId) {
  if (!state.live || !runId || runId === state.data.crawl.id) return;
  try {
    const next = await fetchSnapshot({ run: runId });
    state.data = next;
    state.selectedId = state.data.pages[0]?.id ?? null;
    // Keep the URL shareable: the selected run stays addressable via ?run=.
    const url = new URL(window.location.href);
    url.searchParams.set("run", runId);
    window.history.replaceState({}, "", url);
    $(".user-chip").textContent = liveChipLabel();
    renderAll();
    toast(`Viewing run ${runId}`);
  } catch (err) {
    toast(`Could not load run ${runId}: ${err.message}`);
    renderRunSelector(); // put the selector back on the run actually shown
  }
}

async function loadMore() {
  const live = state.data.live;
  if (!live?.hasMore) return;
  const btn = $("#btn-load-more");
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    const next = await fetchSnapshot({ run: live.runId, offset: live.windowEnd, limit: live.limit });
    // Append the next window; overview/issues are whole-run aggregates from the
    // server, so they need no client-side recomputation.
    state.data.pages = state.data.pages.concat(next.pages);
    state.data.live = next.live;
    renderTable();
    renderLiveNote();
    renderStatusbar();
  } catch (err) {
    toast(`Could not load more URLs: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Load more";
  }
}

function renderAll() {
  renderNav();
  renderCrawlBar();
  renderCategoryTabs();
  renderTable();
  renderSidebar();
  renderDetail();
  renderStatusbar();
  renderLiveNote();
}

async function main() {
  const params = new URLSearchParams(window.location.search);
  const intentOnly = params.get("view") === "intent-overlap";
  state.intentDataset = params.get("dataset") === "thompsons" ? "thompsons" : "fixture";
  state.live = params.get("live") === "1";
  // Optional ?limit= sets the page-window size; the server clamps it.
  state.pageLimit = params.get("limit") || null;
  initialiseTheme();
  if (intentOnly) {
    // The report fixture is imported by this module, so this route does not
    // fetch sample-data.json and remains suitable for an offline report view.
    state.data = INTENT_ONLY_DATA;
    bindEvents();
    $(".crawl-bar").hidden = true;
    $(".statusbar").hidden = true;
    showIntentOverlap();
    return;
  }

  try {
    if (state.live) {
      state.data = await fetchSnapshot({ run: params.get("run") });
    } else {
      const res = await fetch("./sample-data.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      state.data = await res.json();
    }
    state.selectedId = state.data.pages[0]?.id ?? null;
    bindEvents();
    renderAll();
    if (state.live) $(".user-chip").textContent = liveChipLabel();
  } catch (err) {
    const source = state.live ? "the live crawler snapshot" : "sample-data.json";
    const remedy = state.live
      ? "Start crawler_gui/server.py with a valid --postgres-dsn, then refresh this page."
      : "Serve this folder over HTTP, e.g.:\n  python3 -m http.server 8765";
    document.body.innerHTML = `<pre style="padding:2rem;color:#f87171">Failed to load ${source}.
${remedy}
${escapeHtml(err.message)}</pre>`;
  }
}

main();
