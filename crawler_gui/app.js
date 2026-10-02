/* crawler_gui — bind sample-data.json into the layout shell */
import { adaptReportData, mountIntentOverlapViewer } from "./intent-overlap.mjs";
import { REPORT_DATA } from "./intent-report-fixture.mjs";

const state = {
  data: null,
  category: "internal",
  sidebar: "overview",
  detail: "url-details",
  selectedId: null,
  filter: "",
  sortKey: "row",
  sortDirection: "asc",
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
  evidenceTask: null,
  evidenceMessage: "",
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

  if (category === "internal" && state.live) {
    // The live bridge records these sources in url_sources.  Seeds are
    // deliberately excluded: this view means discovered from a site link or
    // XML sitemap, rather than every URL in the crawl run.
    rows = rows.filter((p) => p.sources?.some((source) => ["link", "sitemap", "robots_sitemap"].includes(source)));
  } else if (category === "archive-org") {
    rows = rows.filter((p) => p.sources?.includes("archive_org"));
  } else if (category === "backlinks") {
    rows = rows.filter((p) => p.sources?.includes("backlink"));
  } else if (["custom-checks", "host-protocol-checks", "url-variant-checks", "fictional-url-checks"].includes(category)) {
    rows = data.customChecks || [];
    const groupByCategory = {
      "host-protocol-checks": "host-protocol",
      "url-variant-checks": "url-variant",
      "fictional-url-checks": "fictional",
    };
    if (groupByCategory[category]) rows = rows.filter((p) => p.checkGroup === groupByCategory[category]);
  } else if (category === "external") {
    rows = rows.flatMap((source) =>
      (source.outlinks || [])
        .filter((link) => link.external)
        .map((link) => ({
          ...source,
          address: link.targetUrl,
          externalTarget: link.targetUrl,
          sourceAddress: source.address,
          anchorText: link.anchorText || "—",
          follow: link.follow === false ? "Nofollow" : "Follow",
        }))
    );
  } else if (category === "social") {
    rows = rows.filter((p) => p.social?.length);
  } else if (category === "javascript") {
    rows = rows.filter((p) => p.scripts?.length);
  } else if (category === "security") {
    rows = rows.filter((p) => !p.address.startsWith("https://"));
  } else if (category !== "internal") {
    rows = rows.filter((p) => (p.categoryHints || []).includes(category));
  }

  const q = filter.trim().toLowerCase();
  if (q) {
    rows = rows.filter((p) =>
      [p.address, p.sourceAddress, p.anchorText, p.title, p.status, p.check, p.protocol, p.hostVariant, p.result, String(p.statusCode), p.contentType]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }
  return rows;
}

const NUMERIC_SORT_COLUMNS = new Set([
  "row",
  "statusCode",
  "responseTimeMs",
  "internalInlinks",
  "externalInlinks",
  "titleLength",
  "metaDescriptionLength",
  "h1Count",
  "h2Count", "imageCount", "schemaCount", "hreflangCount", "socialCount", "scriptCount", "externalOutlinkCount", "wordCount",
]);

function sortValue(page, key, rowIndex) {
  if (key === "row") return rowIndex;
  if (["sources", "sourceEvidence", "schemaTypes", "languages", "ogTitle", "twitterCard"].includes(key)) return cellValue(page, key, rowIndex);
  const computed = {imageCount: "images", schemaCount: "structuredData", hreflangCount: "hreflang", socialCount: "social", scriptCount: "scripts"};
  if (computed[key]) return (page[computed[key]] || []).length;
  if (key === "externalOutlinkCount") return (page.outlinks || []).filter((link) => link.external).length;
  return page[key];
}

function sortPages(pages) {
  const { sortKey, sortDirection } = state;
  return pages
    .map((page, index) => ({ page, index, value: sortValue(page, sortKey, index) }))
    .sort((a, b) => {
      const aBlank = a.value == null || a.value === "";
      const bBlank = b.value == null || b.value === "";
      if (aBlank || bBlank) {
        if (aBlank && bBlank) return a.index - b.index;
        return aBlank ? 1 : -1;
      }
      let comparison;
      if (NUMERIC_SORT_COLUMNS.has(sortKey)) {
        comparison = Number(a.value) - Number(b.value);
      } else {
        comparison = String(a.value).localeCompare(String(b.value), undefined, { numeric: true, sensitivity: "base" });
      }
      return comparison === 0 ? a.index - b.index : comparison * (sortDirection === "asc" ? 1 : -1);
    })
    .map(({ page }) => page);
}

function columnsForCategory(cat) {
  if (cat === "external") {
    return [
      { key: "row", label: "#" },
      { key: "externalTarget", label: "Destination URL" },
      { key: "sourceAddress", label: "Source URL" },
      { key: "anchorText", label: "Anchor text" },
      { key: "follow", label: "Follow" },
    ];
  }
  if (["custom-checks", "host-protocol-checks", "url-variant-checks", "fictional-url-checks"].includes(cat)) {
    return [
      { key: "row", label: "#" },
      { key: "check", label: "Check" },
      { key: "address", label: "Attempted URL" },
      { key: "protocol", label: "Protocol" },
      { key: "hostVariant", label: "Host variant" },
      { key: "statusCode", label: "Status Code" },
      { key: "status", label: "Status" },
      { key: "redirectUrl", label: "Redirect URL" },
      { key: "result", label: "Recorded result" },
    ];
  }
  const base = [
    { key: "row", label: "#" },
    { key: "address", label: "Address" },
  ];
  const reportColumns = {
    "structured-data": [["schemaCount", "Items"], ["schemaTypes", "Types"], ["title", "Title"]],
    h2: [["h2Count", "H2 Count"], ["h2", "H2 headings"], ["title", "Title"]],
    images: [["imageCount", "Image references"], ["title", "Page title"]],
    hreflang: [["hreflangCount", "Alternates"], ["languages", "Languages"], ["title", "Title"]],
    social: [["ogTitle", "Open Graph title"], ["twitterCard", "Twitter card"], ["socialCount", "Social tags"]],
    javascript: [["scriptCount", "Saved script references"], ["title", "Title"]],
    sitemaps: [["sourceEvidence", "Source evidence"], ["statusCode", "Status Code"], ["title", "Title"]],
    canonicals: [["canonical", "Canonical URL"], ["indexability", "Indexability"]],
    directives: [["robots", "Recorded directives"], ["indexability", "Indexability"]],
    content: [["wordCount", "Words"], ["title", "Title"]],
  };
  if (reportColumns[cat]) return [...base, ...reportColumns[cat].map(([key, label]) => ({ key, label }))];
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
  if (cat === "internal" || cat === "archive-org" || cat === "backlinks") {
    return [
      ...base,
      { key: "sources", label: "Discovery Source" },
      { key: "sourceEvidence", label: "Source evidence" },
      ...(cat === "backlinks" ? [{ key: "externalInlinks", label: "Backlinks" }] : []),
      { key: "statusCode", label: "Status Code" },
      { key: "status", label: "Status" },
      { key: "indexability", label: "Indexability" },
      { key: "title", label: "Title" },
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
  const computed = {imageCount: "images", schemaCount: "structuredData", hreflangCount: "hreflang", socialCount: "social", scriptCount: "scripts"};
  if (computed[key]) return (page[computed[key]] || []).length;
  if (key === "externalOutlinkCount") return (page.outlinks || []).filter((link) => link.external).length;
  if (key === "schemaTypes") return [...new Set((page.structuredData || []).map((item) => item.type))].join(", ");
  if (key === "languages") return [...new Set((page.hreflang || []).map((item) => item.hreflang))].join(", ");
  if (key === "ogTitle" || key === "twitterCard") return page.social?.find((item) => item.property === (key === "ogTitle" ? "og:title" : "twitter:card"))?.content || "—";
  if (key === "sources") {
    const labels = {
      link: "Internal link",
      sitemap: "XML sitemap",
      robots_sitemap: "robots.txt sitemap",
      archive_org: "Archive.org",
      backlink: "Backlink export",
      custom_check: "Custom status check",
      seed: "Seed URL",
    };
    return (page.sources || []).map((source) => labels[source] || source).join(", ");
  }
  if (key === "sourceEvidence") {
    const details = [...new Set((page.sourceEvidence || []).map((item) => `${item.scope === "database" ? "Database-wide: " : ""}${item.detail || item.source}`).filter(Boolean))];
    if (details.length <= 3) return details.join(", ") || "—";
    return `${details.slice(0, 3).join(", ")} +${details.length - 3}`;
  }
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
  const pct = state.live ? (state.data.live?.totalPages ? 100 * state.data.pages.length / state.data.live.totalPages : 0) : c.progress.pct;
  $("#mini-progress-fill").style.width = `${pct}%`;
  $("#mini-progress-label").textContent = `${Math.round(pct)}%`;
  renderRunSelector();
  $("#btn-resume").hidden = !state.live || !state.data.live?.snapshotBacked;
  for (const id of ["#btn-new-schedule", "#btn-delete"]) {
    $(id).disabled = state.live;
    $(id).title = state.live ? "Not available in this local GUI" : "";
  }
  const schedule = $("#nav-links [data-nav='schedule']");
  if (schedule && state.live) { schedule.disabled = true; schedule.title = "Scheduling is not connected"; }
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
  const pages = sortPages(filteredPages());
  const cols = columnsForCategory(state.category);
  $("#filter-total").textContent = `Filter Total: ${pages.length}`;
  const notes = [];
  if (state.live && state.data.live?.hasMore) notes.push("Filters and sorting apply to loaded URLs. Load all for the full run.");
  if (["internal", "sitemaps", "archive-org", "backlinks"].includes(state.category) && state.data.pages.some((p) => p.sourceEvidence?.some((item) => item.scope === "database"))) notes.push("Database-wide source evidence is labelled; it may come from another run or import.");
  if (["custom-checks", "host-protocol-checks", "url-variant-checks", "fictional-url-checks"].includes(state.category) && (state.data.customChecks || []).some((p) => p.sourceEvidence?.some((item) => item.scope === "database"))) notes.push("Database-wide custom-check evidence is labelled; it may come from another run or import.");
  if (["social", "javascript", "external"].includes(state.category)) notes.push(state.evidenceMessage || "Recovered from saved HTML. Select a row for details.");
  if (state.category === "javascript") notes.push("Script references are shown here; these are not JavaScript-discovered crawl URLs.");
  if (state.category === "security") notes.push("This is HTTPS transport screening only. Security findings will appear in a dedicated view once recorded for a run.");
  if (["custom-checks", "host-protocol-checks", "url-variant-checks", "fictional-url-checks"].includes(state.category) && !pages.length) notes.push("No run-scoped custom-probe results are stored for this view. Viewing these tabs never runs a probe or infers one from URL sources.");
  $("#grid-note").textContent = notes.join(" ");
  $("#grid-note").hidden = !notes.length;

  const thead = `<tr>${cols
    .map((c) => {
      const active = c.key === state.sortKey;
      const direction = active ? state.sortDirection : "none";
      const directionLabel = direction === "asc" ? "ascending" : "descending";
      const indicator = active ? (state.sortDirection === "asc" ? " ▲" : " ▼") : "";
      return `<th aria-sort="${direction === "none" ? "none" : directionLabel}"><button type="button" class="sort-header${
        active ? " active" : ""
      }" data-sort="${escapeHtml(c.key)}" aria-label="Sort by ${escapeHtml(c.label)}${
        active ? `, currently ${directionLabel}` : ""
      }">${escapeHtml(c.label)}<span aria-hidden="true">${indicator}</span></button></th>`;
    })
    .join("")}</tr>`;
  const tbody = pages
    .map((p, i) => {
      const selected = p.id === state.selectedId ? " selected" : "";
      const cells = cols
        .map((c) => {
          const cls = cellClass(p, c.key);
          const value = escapeHtml(cellValue(p, c.key, i + 1));
          return `<td class="${cls}" title="${value}">${value}</td>`;
        })
        .join("");
      return `<tr data-id="${p.id}" class="${selected}">${cells}</tr>`;
    })
    .join("");

  $("#grid-head").innerHTML = thead;
  $("#grid-body").innerHTML = tbody || `<tr><td colspan="${cols.length}" class="muted">${state.evidenceTask && ["social", "javascript", "external"].includes(state.category) ? "Reading saved HTML…" : "No matching evidence in the loaded URLs."}</td></tr>`;
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
  return state.data.pages.find((p) => p.id === state.selectedId)
    || (state.data.customChecks || []).find((p) => p.id === state.selectedId)
    || null;
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
    body.innerHTML = (state.live ? '<p class="muted">Internal inlinks reflect the latest stored link graph, which may include other runs.</p>' : "") + linkTable(
      ["Source URL", "Anchor Text", "Follow"],
      (page.inlinks || []).map((l) => [l.sourceUrl, l.anchorText, l.follow ? "True" : "False"])
    );
  } else if (state.detail === "outlinks") {
    body.innerHTML = (state.live ? `<p class="muted">${escapeHtml(page.evidenceNote || "Reading outlinks from this run’s saved HTML…")}</p>` : "") + linkTable(
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
    const rows = (page.structuredData || []).map((s) => [s.type, s.name || s.headline || "", s.format || "", s.is_valid == null ? "Not recorded" : s.is_valid ? "Valid" : "Invalid", (s.validation_errors || []).join("; ")]);
    body.innerHTML = rows.length
      ? linkTable(["Type", "Name / Headline", "Format", "Parser validation", "Errors"], rows)
      : `<p class="muted">No structured data on this URL.</p>`;
  } else if (state.detail === "images") {
    body.innerHTML = linkTable(["Image URL", "Alt", "Alt present", "Width", "Height"], (page.images || []).map((item) => [item.url, item.alt || "", item.alt_present ? "Yes" : "No", item.width ?? "", item.height ?? ""]));
  } else if (state.detail === "hreflang") {
    body.innerHTML = linkTable(["Language", "Alternate URL", "Source"], (page.hreflang || []).map((item) => [item.hreflang, item.href, item.source]));
  } else if (state.detail === "sources") {
    body.innerHTML = linkTable(["Source", "Evidence", "Scope"], (page.sourceEvidence || []).map((item) => [item.source, item.detail || "—", item.scope === "database" ? "Database-wide; not attributed to this run" : "This run"]));
  } else if (state.detail === "social" || state.detail === "javascript") {
    if (!page.evidenceLoaded && state.live) {
      body.innerHTML = '<p class="muted">Reading this URL’s saved HTML…</p>';
    } else {
      body.innerHTML = `<p class="muted">${escapeHtml(page.evidenceNote || "Saved crawl evidence")}</p>` + (state.detail === "social"
        ? linkTable(["Property", "Content"], (page.social || []).map((item) => [item.property, item.content]))
        : linkTable(["Script URL", "Type"], (page.scripts || []).map((item) => [item.url, item.type])));
    }
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
  $("#btn-load-all").hidden = !state.live || !live?.hasMore;
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
  if (state.live) {
    $("#status-avg").textContent = "Saved results";
    $("#status-cur").textContent = "";
    const loaded = state.data.pages.length, total = state.data.live?.totalPages || 0;
    $("#status-fill").style.width = `${total ? 100 * loaded / total : 0}%`;
    $("#status-fill-label").textContent = `${loaded} of ${total} saved URLs loaded`;
    return;
  }
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
    state.sortKey = "row";
    state.sortDirection = "asc";
    const detailForCategory = {"structured-data": "structured-data", social: "social", images: "images", hreflang: "hreflang", javascript: "javascript", external: "outlinks", sitemaps: "sources", backlinks: "sources", "archive-org": "sources", "custom-checks": "sources", "host-protocol-checks": "sources", "url-variant-checks": "sources", "fictional-url-checks": "sources"};
    state.detail = detailForCategory[state.category] || "url-details";
    renderCategoryTabs();
    renderTable();
    state.selectedId = filteredPages()[0]?.id ?? null;
    renderTable();
    renderDetail();
    ensureEvidence();
  });

  $("#grid-head").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-sort]");
    if (!btn) return;
    const key = btn.dataset.sort;
    if (state.sortKey === key) {
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortDirection = "asc";
    }
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
    ensureEvidence();
  });

  $("#grid-body").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    state.selectedId = Number(tr.dataset.id);
    renderTable();
    renderDetail();
    ensureEvidence();
  });

  $("#grid-filter").addEventListener("input", (e) => {
    state.filter = e.target.value;
    if (!filteredPages().some((page) => page.id === state.selectedId)) state.selectedId = filteredPages()[0]?.id ?? null;
    renderTable();
    renderDetail();
  });

  $("#btn-history").addEventListener("click", () => {
    renderHistoryModal();
    openModal("#modal-history");
  });

  $("#btn-load-more").addEventListener("click", loadMore);
  $("#btn-resume").addEventListener("click", async () => {
    const run = state.data.crawl.id;
    $("#modal-resume").dataset.run = run;
    $("#resume-summary").textContent = "Checking saved queue…";
    $("#btn-confirm-resume").disabled = true;
    openModal("#modal-resume");
    try {
      const response = await fetch(`./api/live/runs/${encodeURIComponent(run)}/resume`, { cache: "no-store" });
      if (!response.ok) throw new Error(await response.text());
      const plan = await response.json();
      $("#resume-summary").textContent = `${plan.queued} queued · ${plan.pending} pending · ${plan.done} done. ${plan.reason || "The saved crawl scope will be preserved. Runtime settings were not saved; review the settings below."}`;
      $("#resume-backend").value = plan.backend;
      $("#btn-confirm-resume").disabled = !plan.canResume;
    } catch (err) { $("#resume-summary").textContent = err.message; }
  });
  $("#btn-confirm-resume").addEventListener("click", async () => {
    const button = $("#btn-confirm-resume");
    button.disabled = true;
    try {
      const response = await fetch(`./api/live/runs/${encodeURIComponent($("#modal-resume").dataset.run)}/resume`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend: $("#resume-backend").value, maxPages: Number($("#resume-max").value), concurrency: Number($("#resume-concurrency").value) }),
      });
      if (!response.ok) throw new Error(await response.text());
      const job = await response.json();
      closeModals();
      pollCrawlJob(job.jobId);
      toast(`Resuming ${job.runId}`);
    } catch (err) {
      $("#resume-summary").textContent = err.message;
      button.disabled = false;
    }
  });
  $("#btn-load-all").addEventListener("click", async () => {
    const data = state.data;
    const button = $("#btn-load-all");
    button.disabled = true;
    button.textContent = "Loading all…";
    try {
      while (state.data === data && data.live?.hasMore) {
        if (!await loadMore()) break;
      }
    } finally {
      button.disabled = false;
      button.textContent = "Load all";
    }
  });

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
    toast(state.configContext === "schedule" ? "Scheduled crawl options saved" : "Settings saved for the next new crawl in this browser session");
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

async function showIntentOverlap() {
  state.view = "intent-overlap";
  $(".stage").hidden = true;
  $("#category-tabs").hidden = true;
  const root = $("#intent-overlap-root");
  root.hidden = false;
  if (!state.intentViewer) {
    const isThompsons = state.intentDataset === "thompsons";
    let report = REPORT_DATA;
    if (isThompsons) {
      try {
        // This export is optional in a checkout.  Loading it lazily keeps the
        // normal crawler UI available when the Thompson fixture is absent.
        ({ REPORT_DATA: report } = await import("./thompsons-intent-report.mjs"));
      } catch (err) {
        root.textContent = `Could not load the Thompsons report fixture: ${err.message}`;
        renderNav();
        return;
      }
    }
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

async function ensureEvidence() {
  if (!state.live || state.evidenceTask) return;
  const data = state.data;
  const pending = () => {
    if (state.data !== data) return [];
    const all = ["social", "javascript", "external"].includes(state.category);
    const selected = ["social", "javascript", "outlinks"].includes(state.detail);
    return data.pages.filter((page) => !page.evidenceLoaded && (all || (selected && page.id === state.selectedId)));
  };
  if (!pending().length) return;
  state.evidenceTask = data;
  try {
    while (pending().length) {
      const batch = pending().slice(0, 100);
      state.evidenceMessage = `Reading saved HTML: ${pending().length} loaded URLs remaining…`;
      renderTable();
      const endpoint = new URL("./api/live/evidence", window.location.href);
      endpoint.searchParams.set("run", data.crawl.id);
      endpoint.searchParams.set("ids", batch.map((page) => page.id).join(","));
      const response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) throw new Error(await response.text());
      const recovered = new Map((await response.json()).pages.map((page) => [page.id, page]));
      for (const page of batch) {
        const evidence = recovered.get(page.id);
        Object.assign(page, evidence || { evidenceLoaded: true, evidenceNote: "No saved snapshot for this URL." });
        if (evidence?.savedOutlinks) page.outlinks = evidence.savedOutlinks;
      }
      if (state.data !== data) break;
      if (!filteredPages().some((p) => p.id === state.selectedId)) state.selectedId = filteredPages()[0]?.id ?? null;
      renderTable();
      renderDetail();
    }
    state.evidenceMessage = "Recovered from this run’s saved HTML. No live website requests.";
  } catch (err) {
    state.evidenceMessage = `Could not read saved HTML: ${err.message}. Reopen the tab to retry.`;
  } finally {
    state.evidenceTask = null;
    renderTable();
    renderDetail();
    if (state.data !== data) ensureEvidence();
  }
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
      await switchRun(preferRunId, true);
    } else {
      state.data.history = runs.map((r) => ({ ...r, viewing: r.id === state.data.crawl.id }));
      renderRunSelector();
    }
  } catch {
    /* Leave the current view intact; the selector still shows known runs. */
  }
}

async function switchRun(runId, force = false) {
  if (!state.live || !runId || (!force && runId === state.data.crawl.id)) return;
  try {
    const next = await fetchSnapshot({ run: runId });
    state.data = next;
    state.evidenceMessage = "";
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
  const data = state.data;
  const live = state.data.live;
  if (!live?.hasMore) return false;
  const btn = $("#btn-load-more");
  if (btn.disabled) return false;
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    const next = await fetchSnapshot({ run: live.runId, offset: live.windowEnd, limit: live.limit });
    if (state.data !== data) return false;
    // Append the next window; overview/issues are whole-run aggregates from the
    // server, so they need no client-side recomputation.
    state.data.pages = state.data.pages.concat(next.pages);
    state.data.live = next.live;
    renderTable();
    renderLiveNote();
    renderStatusbar();
    renderCrawlBar();
    ensureEvidence();
    return true;
  } catch (err) {
    toast(`Could not load more URLs: ${err.message}`);
    return false;
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
  ensureEvidence();
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
