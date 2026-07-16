"""Self-contained interactive HTML cluster report (ticket 107).

Renders ``report_data.json`` (ticket 106) as a single offline HTML file:
canvas cluster map + filter panel + sortable pages/pairs/clusters tables.
Zero network at render and at view time — no CDN, no external fonts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_HTML_VERSION = "1.0.0"

# Approximate tested ceiling documented in README (ticket 107).
DOCUMENTED_PAGE_LIMIT = 5000
DOCUMENTED_PAIR_LIMIT = 2000


def _embed_json(data: dict[str, Any]) -> str:
    """Serialize *data* for a ``<script type="application/json">`` block."""
    # Escape ``<`` so a URL/string cannot close the script tag early.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_report_html(data: dict[str, Any]) -> str:
    """Return a full self-contained HTML document for *data*."""
    payload = _embed_json(data)
    return _HTML_TEMPLATE.replace("__REPORT_JSON__", payload).replace("__REPORT_HTML_VERSION__", REPORT_HTML_VERSION)


def write_report_html(
    data: dict[str, Any] | str | Path,
    out_path: str | Path,
) -> Path:
    """Load or accept report JSON and write a self-contained HTML file."""
    if isinstance(data, (str, Path)):
        path = Path(data)
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        report = data
    if not isinstance(report, dict):
        raise ValueError("report data must be a JSON object")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = render_report_html(report)
    out.write_text(html, encoding="utf-8")
    size = out.stat().st_size
    n_pages = len(report.get("pages") or [])
    n_pairs = len(report.get("pairs") or [])
    logger.info(
        "report.html written (%s bytes, %s pages, %s pairs)",
        size,
        n_pages,
        n_pairs,
    )
    if n_pages > DOCUMENTED_PAGE_LIMIT or n_pairs > DOCUMENTED_PAIR_LIMIT:
        logger.warning(
            "report size above documented laptop target (~%s pages / ~%s pairs); "
            "map may drop below 60fps on modest hardware",
            DOCUMENTED_PAGE_LIMIT,
            DOCUMENTED_PAIR_LIMIT,
        )
    return out


# ---------------------------------------------------------------------------
# Template (inline CSS + JS; no external resources)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Intent-overlap cluster report</title>
<style>
:root {
  --bg: #f3efe6;
  --ink: #1c1915;
  --muted: #5c564c;
  --panel: #fffdf8;
  --line: #d7d0c3;
  --accent: #0f6b5c;
  --accent-soft: #d7efe9;
  --danger: #8b2e1f;
  --warn: #8a5a12;
  --map-bg: #e8e2d6;
  --font: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  --mono: "IBM Plex Mono", "Consolas", "Liberation Mono", monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(ellipse at 10% 0%, #efe6d4 0%, transparent 55%),
    radial-gradient(ellipse at 90% 20%, #dfece7 0%, transparent 45%),
    var(--bg);
  font-family: var(--font);
  line-height: 1.45;
}
noscript {
  display: block;
  padding: 1rem 1.25rem;
  background: #f7e6e2;
  border-bottom: 1px solid #e0b4aa;
  color: var(--danger);
}
header.summary {
  padding: 1.25rem 1.5rem 1rem;
  border-bottom: 1px solid var(--line);
}
header.summary h1 {
  margin: 0 0 0.35rem;
  font-size: 1.55rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}
header.summary p {
  margin: 0.2rem 0;
  color: var(--muted);
  font-size: 0.95rem;
}
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1.25rem;
  margin-top: 0.75rem;
  font-family: var(--mono);
  font-size: 0.78rem;
}
.stats span strong { color: var(--ink); font-weight: 600; }
.layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 0;
  min-height: calc(100vh - 8rem);
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
aside.filters {
  border-right: 1px solid var(--line);
  background: var(--panel);
  padding: 1rem 1rem 2rem;
  overflow: auto;
  max-height: calc(100vh - 8rem);
}
aside.filters h2 {
  margin: 0 0 0.6rem;
  font-size: 0.95rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}
aside.filters h3 {
  margin: 1rem 0 0.4rem;
  font-size: 0.82rem;
  color: var(--muted);
}
.field { margin-bottom: 0.55rem; }
.field label {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  font-size: 0.88rem;
  cursor: pointer;
}
.field .count {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 0.75rem;
  color: var(--muted);
}
input[type="search"], select {
  width: 100%;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: #fff;
  font: inherit;
  color: var(--ink);
}
.cluster-list {
  max-height: 12rem;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0.35rem;
  background: #fff;
}
main.viewer { display: flex; flex-direction: column; min-width: 0; }
.map-wrap {
  position: relative;
  background: var(--map-bg);
  border-bottom: 1px solid var(--line);
  height: min(52vh, 520px);
  min-height: 280px;
}
#map {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
}
#map.dragging { cursor: grabbing; }
.tooltip {
  position: absolute;
  z-index: 5;
  max-width: 28rem;
  padding: 0.55rem 0.7rem;
  background: #1c1915;
  color: #f7f2e8;
  border-radius: 4px;
  font-size: 0.8rem;
  pointer-events: none;
  display: none;
  box-shadow: 0 8px 24px rgba(28,25,21,0.25);
}
.tooltip code { font-family: var(--mono); font-size: 0.72rem; word-break: break-all; }
.tooltip .meta { color: #cfc6b6; margin-top: 0.25rem; }
.map-hint {
  position: absolute;
  left: 0.75rem;
  bottom: 0.6rem;
  font-size: 0.72rem;
  color: var(--muted);
  background: rgba(255,253,248,0.82);
  padding: 0.2rem 0.45rem;
  border-radius: 3px;
}
.tables {
  padding: 0.75rem 1rem 2rem;
  flex: 1;
  min-height: 0;
}
.tabs {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 0.65rem;
  flex-wrap: wrap;
}
.tabs button {
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--ink);
  padding: 0.35rem 0.7rem;
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
  font-size: 0.85rem;
}
.tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.table-scroll {
  overflow: auto;
  max-height: min(42vh, 420px);
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
th, td {
  padding: 0.4rem 0.55rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
th {
  position: sticky;
  top: 0;
  background: #f7f1e6;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
th.sorted-asc::after { content: " ↑"; }
th.sorted-desc::after { content: " ↓"; }
tr:hover td { background: var(--accent-soft); }
tr.selected td { background: #cfe6df; }
td.url, td.mono { font-family: var(--mono); font-size: 0.74rem; word-break: break-all; }
.empty {
  padding: 1rem;
  color: var(--muted);
  font-size: 0.9rem;
}
</style>
</head>
<body>
<noscript>JavaScript is required for the interactive cluster map and filterable tables. The summary below is still available from the embedded report JSON.</noscript>
<header class="summary" id="summary-card">
  <h1>Intent-overlap cluster report</h1>
  <p id="summary-line">Loading…</p>
  <div class="stats" id="summary-stats"></div>
</header>
<div class="layout">
  <aside class="filters" id="filters">
    <h2>Filters</h2>
    <div class="field">
      <label for="url-search">URL contains</label>
      <input type="search" id="url-search" placeholder="e.g. /videos" autocomplete="off">
    </div>
    <h3>Risk</h3>
    <div class="field">
      <select id="risk-mode" aria-label="Risk filter">
        <option value="all">All risks</option>
        <option value="duplicate">Duplicate / parent-child</option>
        <option value="overlap">High overlap + duplicate</option>
      </select>
    </div>
    <h3>Match / page types</h3>
    <div id="type-filters"></div>
    <h3>Clusters</h3>
    <div class="field">
      <label><input type="checkbox" id="cluster-all" checked> All clusters</label>
    </div>
    <div class="cluster-list" id="cluster-filters"></div>
  </aside>
  <main class="viewer">
    <div class="map-wrap">
      <canvas id="map" aria-label="Cluster map"></canvas>
      <div class="tooltip" id="tooltip"></div>
      <div class="map-hint">Wheel zoom · drag pan · click to pin · hover highlights cluster mates</div>
    </div>
    <section class="tables">
      <div class="tabs" role="tablist">
        <button type="button" class="active" data-tab="pages">Pages</button>
        <button type="button" data-tab="pairs">Pairs</button>
        <button type="button" data-tab="clusters">Clusters</button>
      </div>
      <div class="table-scroll">
        <div id="table-root"></div>
      </div>
    </section>
  </main>
</div>
<script type="application/json" id="report-data">__REPORT_JSON__</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("report-data").textContent);
  var pages = data.pages || [];
  var pairs = data.pairs || [];
  var clusters = data.clusters || [];
  var summary = data.summary || {};
  var clusterById = {};
  clusters.forEach(function (c) { clusterById[c.id] = c; });

  var TYPE_FILTERS = [
    { id: "parent-child", label: "parent-child", kind: "relation", def: true },
    { id: "sibling", label: "sibling", kind: "relation", def: true },
    { id: "same-section", label: "same-section", kind: "relation", def: true },
    { id: "cross-section", label: "cross-section", kind: "relation", def: true },
    { id: "time-sequenced", label: "time-sequenced", kind: "pair_class", def: true },
    { id: "thin", label: "thin", kind: "thin", def: true },
    { id: "parameterised", label: "parameterised", kind: "url_class", def: true },
    { id: "amp-variant", label: "amp-variant", kind: "amp", def: false },
    { id: "excluded", label: "excluded pages", kind: "excluded", def: false },
    { id: "off-topic", label: "off-topic", kind: "off_topic", def: true }
  ];

  var state = {
    search: "",
    risk: "all",
    types: {},
    clusters: {},
    allClusters: true,
    tab: "pages",
    sort: { pages: { key: "max_similarity", dir: -1 }, pairs: { key: "similarity", dir: -1 }, clusters: { key: "size", dir: -1 } },
    hoverIdx: -1,
    pinnedIdx: -1,
    view: { scale: 1, tx: 0, ty: 0 },
    dragging: false,
    lastX: 0,
    lastY: 0
  };
  TYPE_FILTERS.forEach(function (f) { state.types[f.id] = f.def; });
  clusters.forEach(function (c) { state.clusters[c.id] = true; });

  function riskBucket(risk) {
    risk = risk || "";
    if (risk.indexOf("duplicate") >= 0 || risk.indexOf("parent-child") >= 0) return "duplicate";
    if (risk.indexOf("overlap") >= 0 || risk.indexOf("thin content") >= 0 || risk.indexOf("time-sequenced") >= 0) return "overlap";
    return "other";
  }

  function pageVisible(p) {
    var isAmp = p.variant_kind === "amp" || p.excluded === "amp-variant";
    if (isAmp) {
      if (!state.types["amp-variant"]) return false;
    } else if (p.excluded) {
      if (!state.types.excluded) return false;
    }
    if (p.off_topic && !state.types["off-topic"]) return false;
    if (p.url_class === "parameterised" && !state.types.parameterised) return false;
    if (!state.allClusters && p.cluster_id && !state.clusters[p.cluster_id]) return false;
    if (!state.allClusters && !p.cluster_id && !p.excluded) return false;
    var q = state.search.trim().toLowerCase();
    if (q && String(p.url || "").toLowerCase().indexOf(q) < 0) return false;
    if (state.risk === "duplicate" && riskBucket(p.risk) !== "duplicate") return false;
    if (state.risk === "overlap") {
      var b = riskBucket(p.risk);
      if (b !== "duplicate" && b !== "overlap") return false;
    }
    return true;
  }

  function pairVisible(pair) {
    var rel = pair.relation || "";
    if (rel === "parent-child" && !state.types["parent-child"]) return false;
    if (rel === "sibling" && !state.types.sibling) return false;
    if (rel === "same-section" && !state.types["same-section"]) return false;
    if (rel === "cross-section" && !state.types["cross-section"]) return false;
    if (pair.pair_class === "time-sequenced" && !state.types["time-sequenced"]) return false;
    if (pair.thin && !state.types.thin) return false;
    var q = state.search.trim().toLowerCase();
    if (q) {
      var hay = (pair.url_a + " " + pair.url_b).toLowerCase();
      if (hay.indexOf(q) < 0) return false;
    }
    var pa = pageByUrl[pair.url_a];
    var pb = pageByUrl[pair.url_b];
    if (pa && !pageVisible(pa)) return false;
    if (pb && !pageVisible(pb)) return false;
    return true;
  }

  function clusterVisible(c) {
    if (!state.allClusters && !state.clusters[c.id]) return false;
    var q = state.search.trim().toLowerCase();
    if (q) {
      var blob = (c.label || "") + " " + (c.urls || []).join(" ");
      if (blob.toLowerCase().indexOf(q) < 0) return false;
    }
    return true;
  }

  var pageByUrl = {};
  pages.forEach(function (p, i) { p._i = i; pageByUrl[p.url] = p; });

  var mappable = pages.filter(function (p) { return p.coords && p.coords.length >= 2; });
  var palette = {};
  function colorFor(cid) {
    if (!cid) return "#7a7468";
    if (palette[cid]) return palette[cid];
    var h = 0;
    for (var i = 0; i < cid.length; i++) h = (h * 31 + cid.charCodeAt(i)) >>> 0;
    var hue = h % 360;
    palette[cid] = "hsl(" + hue + " 48% 38%)";
    return palette[cid];
  }

  /* ---- summary ---- */
  function renderSummary() {
    var model = data.embedding_model || summary.model || "unknown model";
    var proj = (data.projection && data.projection.method) || "n/a";
    document.getElementById("summary-line").textContent =
      model + " · projection " + proj + " · generated " + (data.generated_at || "n/a");
    var bits = [
      ["embedded", summary.embedded],
      ["pairs", summary.overlap_pairs],
      ["clusters", summary.clusters],
      ["duplicates", summary.duplicate_pages],
      ["thin", summary.thin_content_pages],
      ["threshold", summary.threshold]
    ];
    document.getElementById("summary-stats").innerHTML = bits.map(function (b) {
      return "<span>" + b[0] + ": <strong>" + (b[1] == null ? "—" : b[1]) + "</strong></span>";
    }).join("");
  }

  /* ---- filters UI ---- */
  function countForType(f) {
    if (f.kind === "relation") return pairs.filter(function (p) { return p.relation === f.id; }).length;
    if (f.kind === "pair_class") return pairs.filter(function (p) { return p.pair_class === f.id; }).length;
    if (f.kind === "thin") return pairs.filter(function (p) { return !!p.thin; }).length +
      pages.filter(function (p) { return String(p.risk || "").indexOf("thin") >= 0; }).length;
    if (f.kind === "url_class") return pages.filter(function (p) { return p.url_class === "parameterised"; }).length;
    if (f.kind === "amp") return pages.filter(function (p) {
      return p.variant_kind === "amp" || p.excluded === "amp-variant";
    }).length;
    if (f.kind === "excluded") return pages.filter(function (p) { return !!p.excluded; }).length;
    if (f.kind === "off_topic") return pages.filter(function (p) { return !!p.off_topic; }).length;
    return 0;
  }

  function buildFilters() {
    var root = document.getElementById("type-filters");
    root.innerHTML = TYPE_FILTERS.map(function (f) {
      return '<div class="field"><label><input type="checkbox" data-type="' + f.id + '"' +
        (state.types[f.id] ? " checked" : "") + "> " + f.label +
        '<span class="count" id="count-' + f.id + '">' + countForType(f) + "</span></label></div>";
    }).join("");
    root.querySelectorAll("input[data-type]").forEach(function (el) {
      el.addEventListener("change", function () {
        state.types[el.getAttribute("data-type")] = el.checked;
        refresh();
      });
    });
    var cl = document.getElementById("cluster-filters");
    cl.innerHTML = clusters.map(function (c) {
      var lab = (c.label || c.id) + " (" + c.size + ")";
      return '<div class="field"><label><input type="checkbox" data-cluster="' + c.id + '" checked> ' +
        escapeHtml(lab) + "</label></div>";
    }).join("") || '<div class="empty">No clusters</div>';
    cl.querySelectorAll("input[data-cluster]").forEach(function (el) {
      el.addEventListener("change", function () {
        state.clusters[el.getAttribute("data-cluster")] = el.checked;
        state.allClusters = false;
        document.getElementById("cluster-all").checked = false;
        refresh();
      });
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  document.getElementById("url-search").addEventListener("input", function (e) {
    state.search = e.target.value;
    refresh();
  });
  document.getElementById("risk-mode").addEventListener("change", function (e) {
    state.risk = e.target.value;
    refresh();
  });
  document.getElementById("cluster-all").addEventListener("change", function (e) {
    state.allClusters = e.target.checked;
    if (state.allClusters) {
      clusters.forEach(function (c) { state.clusters[c.id] = true; });
      document.querySelectorAll("#cluster-filters input[data-cluster]").forEach(function (el) {
        el.checked = true;
      });
    }
    refresh();
  });

  /* ---- tables ---- */
  document.querySelectorAll(".tabs button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.tab = btn.getAttribute("data-tab");
      document.querySelectorAll(".tabs button").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      renderTable();
    });
  });

  function sortRows(rows, tab) {
    var s = state.sort[tab];
    var key = s.key, dir = s.dir;
    return rows.slice().sort(function (a, b) {
      var va = a[key], vb = b[key];
      if (va == null) va = "";
      if (vb == null) vb = "";
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * dir;
    });
  }

  function renderTable() {
    var root = document.getElementById("table-root");
    if (state.tab === "pages") {
      var rows = sortRows(pages.filter(pageVisible), "pages");
      root.innerHTML = tableHtml(
        ["url", "cluster_id", "risk", "url_class", "word_count", "signature_words", "max_similarity", "centroid_similarity"],
        rows.map(function (p) {
          return {
            url: p.url, cluster_id: p.cluster_id || "", risk: p.risk || "",
            url_class: p.url_class || "", word_count: p.word_count,
            signature_words: p.signature_words, max_similarity: p.max_similarity,
            centroid_similarity: p.centroid_similarity, _i: p._i
          };
        }),
        "pages"
      );
    } else if (state.tab === "pairs") {
      var prows = sortRows(pairs.filter(pairVisible), "pairs");
      root.innerHTML = tableHtml(
        ["url_a", "url_b", "similarity", "relation", "pair_class", "thin", "sim_percentile"],
        prows,
        "pairs"
      );
    } else {
      var crows = sortRows(clusters.filter(clusterVisible), "clusters");
      root.innerHTML = tableHtml(
        ["id", "label", "size", "relation", "thin", "time_sequenced", "suggested_canonical"],
        crows,
        "clusters"
      );
    }
    root.querySelectorAll("th[data-key]").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-key");
        var s = state.sort[state.tab];
        if (s.key === key) s.dir = -s.dir;
        else { s.key = key; s.dir = key === "url" || key === "url_a" || key === "label" || key === "id" ? 1 : -1; }
        renderTable();
      });
    });
    root.querySelectorAll("tr[data-page-i]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        var idx = Number(tr.getAttribute("data-page-i"));
        state.pinnedIdx = idx;
        focusPage(idx);
        drawMap();
        renderTable();
      });
    });
    root.querySelectorAll("tr[data-cluster-id]").forEach(function (tr) {
      tr.addEventListener("click", function () {
        var cid = tr.getAttribute("data-cluster-id");
        var first = mappable.find(function (p) { return p.cluster_id === cid && pageVisible(p); });
        if (first) {
          state.pinnedIdx = first._i;
          focusPage(first._i);
          drawMap();
        }
      });
    });
  }

  function tableHtml(cols, rows, tab) {
    if (!rows.length) return '<div class="empty">No rows match the current filters.</div>';
    var s = state.sort[tab];
    var head = cols.map(function (c) {
      var cls = s.key === c ? (s.dir > 0 ? "sorted-asc" : "sorted-desc") : "";
      return '<th class="' + cls + '" data-key="' + c + '">' + c + "</th>";
    }).join("");
    var body = rows.map(function (r) {
      var attrs = "";
      if (tab === "pages") {
        attrs = ' data-page-i="' + r._i + '"' + (state.pinnedIdx === r._i ? ' class="selected"' : "");
      } else if (tab === "clusters") {
        attrs = ' data-cluster-id="' + escapeHtml(r.id) + '"';
      }
      var cells = cols.map(function (c) {
        var v = r[c];
        var cls = (c.indexOf("url") === 0 || c === "id" || c === "suggested_canonical") ? "url" : "";
        return '<td class="' + cls + '">' + escapeHtml(v == null ? "" : v) + "</td>";
      }).join("");
      return "<tr" + attrs + ">" + cells + "</tr>";
    }).join("");
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  /* ---- map ---- */
  var canvas = document.getElementById("map");
  var ctx = canvas.getContext("2d");
  var tooltip = document.getElementById("tooltip");
  var bounds = { minX: 0, maxX: 1, minY: 0, maxY: 1 };

  function computeBounds() {
    var xs = [], ys = [];
    mappable.forEach(function (p) {
      xs.push(p.coords[0]); ys.push(p.coords[1]);
    });
    if (!xs.length) return;
    bounds.minX = Math.min.apply(null, xs);
    bounds.maxX = Math.max.apply(null, xs);
    bounds.minY = Math.min.apply(null, ys);
    bounds.maxY = Math.max.apply(null, ys);
    if (bounds.minX === bounds.maxX) { bounds.minX -= 1; bounds.maxX += 1; }
    if (bounds.minY === bounds.maxY) { bounds.minY -= 1; bounds.maxY += 1; }
  }

  function resize() {
    var rect = canvas.parentElement.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawMap();
  }

  function worldToScreen(x, y, w, h) {
    var nx = (x - bounds.minX) / (bounds.maxX - bounds.minX);
    var ny = (y - bounds.minY) / (bounds.maxY - bounds.minY);
    var pad = 24;
    var sx = pad + nx * (w - 2 * pad);
    var sy = pad + (1 - ny) * (h - 2 * pad);
    return {
      x: sx * state.view.scale + state.view.tx,
      y: sy * state.view.scale + state.view.ty
    };
  }

  function drawMap() {
    var w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    var visiblePairs = pairs.filter(pairVisible);
    var hover = state.hoverIdx >= 0 ? pages[state.hoverIdx] : null;
    var pin = state.pinnedIdx >= 0 ? pages[state.pinnedIdx] : null;
    var focus = hover || pin;

    if (focus && focus.coords) {
      visiblePairs.forEach(function (pair) {
        if (pair.url_a !== focus.url && pair.url_b !== focus.url) return;
        var a = pageByUrl[pair.url_a], b = pageByUrl[pair.url_b];
        if (!a || !b || !a.coords || !b.coords) return;
        if (!pageVisible(a) || !pageVisible(b)) return;
        var sa = worldToScreen(a.coords[0], a.coords[1], w, h);
        var sb = worldToScreen(b.coords[0], b.coords[1], w, h);
        ctx.beginPath();
        ctx.moveTo(sa.x, sa.y);
        ctx.lineTo(sb.x, sb.y);
        ctx.strokeStyle = "rgba(15,107,92,0.35)";
        ctx.lineWidth = 1;
        ctx.stroke();
      });
    }

    mappable.forEach(function (p) {
      if (!pageVisible(p)) return;
      var s = worldToScreen(p.coords[0], p.coords[1], w, h);
      var mate = focus && focus.cluster_id && p.cluster_id === focus.cluster_id;
      var r = (focus && focus.url === p.url) ? 6 : (mate ? 5 : 3.2);
      ctx.beginPath();
      ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
      ctx.fillStyle = colorFor(p.cluster_id);
      ctx.globalAlpha = focus && !mate && focus.url !== p.url ? 0.25 : 0.9;
      ctx.fill();
      ctx.globalAlpha = 1;
      if (focus && focus.url === p.url) {
        ctx.strokeStyle = "#1c1915";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    });
  }

  function hitTest(mx, my) {
    var w = canvas.clientWidth, h = canvas.clientHeight;
    var best = -1, bestD = 10;
    mappable.forEach(function (p) {
      if (!pageVisible(p)) return;
      var s = worldToScreen(p.coords[0], p.coords[1], w, h);
      var d = Math.hypot(s.x - mx, s.y - my);
      if (d < bestD) { bestD = d; best = p._i; }
    });
    return best;
  }

  function showTooltip(idx, mx, my) {
    if (idx < 0) { tooltip.style.display = "none"; return; }
    var p = pages[idx];
    var cl = p.cluster_id ? (clusterById[p.cluster_id] || {}) : {};
    tooltip.style.display = "block";
    tooltip.style.left = Math.min(mx + 14, canvas.clientWidth - 280) + "px";
    tooltip.style.top = Math.min(my + 14, canvas.clientHeight - 120) + "px";
    tooltip.innerHTML = "<code>" + escapeHtml(p.url) + "</code>" +
      '<div class="meta">' + escapeHtml(cl.label || p.cluster_id || "unclustered") +
      " · " + escapeHtml(p.risk || "no risk") +
      (p.url_class ? " · " + escapeHtml(p.url_class) : "") +
      (p.variant_kind ? " · " + escapeHtml(p.variant_kind) : "") +
      (p.excluded ? " · excluded:" + escapeHtml(p.excluded) : "") +
      "<br>words " + (p.word_count == null ? "—" : p.word_count) +
      " · sig " + (p.signature_words == null ? "—" : p.signature_words) +
      " · centroid " + (p.centroid_similarity == null ? "—" : p.centroid_similarity) +
      "</div>";
  }

  function focusPage(idx) {
    var p = pages[idx];
    if (!p || !p.coords) return;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    var s = worldToScreen(p.coords[0], p.coords[1], w, h);
    state.view.tx += (w / 2) - s.x;
    state.view.ty += (h / 2) - s.y;
  }

  canvas.addEventListener("mousemove", function (e) {
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left, my = e.clientY - rect.top;
    if (state.dragging) {
      state.view.tx += mx - state.lastX;
      state.view.ty += my - state.lastY;
      state.lastX = mx; state.lastY = my;
      drawMap();
      return;
    }
    var idx = hitTest(mx, my);
    state.hoverIdx = idx;
    showTooltip(idx >= 0 ? idx : state.pinnedIdx, mx, my);
    drawMap();
  });
  canvas.addEventListener("mouseleave", function () {
    state.hoverIdx = -1;
    if (state.pinnedIdx < 0) tooltip.style.display = "none";
    drawMap();
  });
  canvas.addEventListener("mousedown", function (e) {
    state.dragging = true;
    canvas.classList.add("dragging");
    var rect = canvas.getBoundingClientRect();
    state.lastX = e.clientX - rect.left;
    state.lastY = e.clientY - rect.top;
  });
  window.addEventListener("mouseup", function () {
    state.dragging = false;
    canvas.classList.remove("dragging");
  });
  canvas.addEventListener("click", function (e) {
    var rect = canvas.getBoundingClientRect();
    var idx = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (idx >= 0) {
      state.pinnedIdx = idx;
      state.tab = "pages";
      document.querySelectorAll(".tabs button").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-tab") === "pages");
      });
      renderTable();
      showTooltip(idx, e.clientX - rect.left, e.clientY - rect.top);
      drawMap();
    }
  });
  canvas.addEventListener("wheel", function (e) {
    e.preventDefault();
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left, my = e.clientY - rect.top;
    var factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    var before = { x: (mx - state.view.tx) / state.view.scale, y: (my - state.view.ty) / state.view.scale };
    state.view.scale = Math.min(12, Math.max(0.4, state.view.scale * factor));
    state.view.tx = mx - before.x * state.view.scale;
    state.view.ty = my - before.y * state.view.scale;
    drawMap();
  }, { passive: false });

  function refresh() {
    renderTable();
    drawMap();
  }

  renderSummary();
  buildFilters();
  computeBounds();
  resize();
  refresh();
  window.addEventListener("resize", resize);
})();
</script>
</body>
</html>
"""
