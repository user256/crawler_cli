# Ticket 107: Self-contained interactive HTML cluster report (hover map + filterable tables)

## Goal
Render `report_data.json` (ticket 106) as a single self-contained HTML file:
an interactive cluster map users can hover to inspect pages and their cluster
mates, with toggles to show/hide match types (parent-child, time-sequenced,
thin, parameterised, AMP, cross-section...), plus the core report tables
(pages/pairs/clusters) as sortable, filterable views. The webpage replacement
for eyeballing six CSVs.

## Background
- Direct user request (2026-07-15): "a cluster map that users can hover over
  to see the various clustered pages together with the ability to turn
  on/off certain types of matches (parent child etc.) and otherwise the
  ability to view all the core report data as a webpage... saving the raw
  data as json over svg."
- The user's prior Colab workflow (plotly 3D scatter over UMAP coords,
  hover = URL, legend entries toggle clusters, duplicate/off-topic overlays)
  is the UX reference — but it needed a notebook, an OpenAI key, and a
  Screaming Frog export. This is the crawler-native, shareable equivalent.
- Ticket 106 supplies everything as one JSON: coords, clusters + derived
  labels, risk/tag fields from tickets 101–105, pair relations, summary.

## Deliverable shape
- New subcommand `crawler-cli render-report --data <report_data.json>
  -o report.html` (also callable via `intent-overlap --html-report` which
  implies `--json-report` and chains both). Separate subcommand matters:
  re-render without re-analysing.
- **One file, fully self-contained, zero network**: inline `<script>` +
  `<style>` + the JSON embedded as a `<script type="application/json">`
  block. No CDN plotly/d3 — the report gets shared with clients and must
  open from a file:// double-click, offline, in any modern browser. That
  rules out heavyweight chart libs unless vendored; prefer a small
  hand-rolled canvas 2D scatter (few hundred lines) over vendoring ~3.5 MB
  of plotly. 2D first; a 3D mode is NOT required (hover precision and
  simplicity beat the Colab's 3D spin).

## Tasks
- **Cluster map** (canvas): one dot per embedded page at its 106 coords,
  coloured by cluster; hover → tooltip with URL, cluster label, risk, tags,
  word/signature counts; hovering a dot highlights its cluster mates and
  (optionally) draws lines to its overlap-pair partners currently visible.
  Click → pins the tooltip / opens the page row in the tables view. Zoom
  (wheel) + pan (drag) since 2–3k dots overlap at fit-all scale.
- **Filter panel** (the core ask): checkboxes to show/hide by pair/page
  type — parent-child, sibling, same-section, cross-section,
  time-sequenced, thin, parameterised, amp-variant, excluded pages,
  off-topic — plus a risk-level selector (duplicate / overlap / all) and a
  cluster picker with the derived labels (the Colab legend-toggle
  equivalent). Filters compose (AND across facets); live counts on each
  checkbox label.
- **Tables view**: pages / pairs / clusters as three tabs, client-side
  sortable columns, text search over URLs, respecting the active filters;
  row click focuses the dot on the map. Include the summary block
  (thresholds, counts, exclusion reasons) as a header card.
- **Search**: a URL substring box that filters both map and tables.
- Keep total JS dependency-free and readable; must degrade gracefully (a
  `<noscript>` note and the summary card in plain HTML).
- Size: report for ~3.3k pages + ~700 pairs should stay well under ~10 MB
  and render at 60fps-ish on a laptop; document tested limits. Above the
  106 size floor the map simply has fewer pair edges — fine.
- Tests: subcommand wiring (golden-ish: output contains embedded JSON and
  key DOM anchors), JSON round-trip (embedded block parses back to the
  input), filter-logic unit tests if filter predicates are generated
  Python-side, an integration-marked test rendering the thompsons run.
- README: document `render-report`, the one-file/offline property, and a
  screenshot-free feature list.

## Definition of Done
- `render-report` over the thompsons-scotland `report_data.json` produces a
  single HTML file that opens offline: hovering a `/videos` dot shows its
  thin tag and cluster mates; unticking "parent-child" hides those 29 pairs'
  edges; the pages table filters to `url_class=parameterised` showing the
  `/the-team` family; AMP/excluded pages are hidden by default but
  toggleable. ruff/mypy/tests green.

## Constraint
100% crawler-powered, zero external requests at render AND at view time.
Report files contain client URLs — they belong in the run's `--out` dir
(untracked), never in git, and must not be published anywhere by tooling.

## Status
planned (2026-07-15) — blocked on ticket 106's stable schema. UX reference:
the user's prior Colab/plotly workflow (hover URLs, legend toggles, duplicate +
off-topic overlays), reimplemented dependency-free.
