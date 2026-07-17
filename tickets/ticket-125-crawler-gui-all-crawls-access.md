# Ticket 125: crawler_gui — complete access to every crawl in a given database

## Goal
Make the GUI's live mode a faithful window onto **all** crawl runs in the
connected PostgreSQL database: every run listed, every run's pages reachable
(not truncated), run-scoped data guaranteed run-scoped, and the bridge itself
landed in the repo with tests instead of living as untracked local WIP.

## Background — current state (evidence, 2026-07-17)

- `crawler_gui/server.py` exists only as **untracked working-tree WIP**: a
  loopback aiohttp bridge with `GET /api/live/runs` (all `crawl_runs` rows,
  newest first, with per-run URL/HTML counts when `page_run_snapshots`
  exists) and `GET /api/live/snapshot?run=…` (rows → the GUI's sample-data
  shape). Solid start — but unlanded, untested, and with known gaps:
  - **Truncation:** snapshot pages are `LIMIT`ed (default 5000, hard cap
    10 000) and only `live.truncated` records the loss. A 40k-page run is
    silently a 5k-page table in the GUI.
  - **Legacy fallback lies about runs:** on DBs without `page_run_snapshots`
    (pre-ticket-095 schema), the pages query reads global current-state
    tables with **no run filter**, and each run row's `urls`/`html_stored`
    counts are the same global numbers — every run claims the whole DB.
  - Inlinks/outlinks, structured data, and response-time fields are stubbed
    (`internalInlinks: 0`, `inlinks: []` …) even where the DB has the data
    (`internal_links`, `page_metadata` timings).
- `app.js` fetches a single snapshot at page load; there is no re-fetch path
  (run switching is a full page reload via `?run=`).
- Local convention is one **database per site** ([[whisk-compare-setup]]);
  "all crawls in a given db" = all runs of that site. Cross-database
  browsing stays out of scope (the bridge takes one DSN).

## Tasks

### A. Land the bridge
- Commit `crawler_gui/server.py` (force-add: `tickets/`-style, `crawler_gui/`
  is tracked) with a README section: usage
  (`python crawler_gui/server.py --postgres-dsn …`), loopback-only posture,
  and the snapshot-vs-legacy schema behaviours.
- Tests: unit-test the row→page mapping and overview aggregation; DSN-gated
  integration test (same `CRAWLER_CLI_TEST_DSN` pattern as
  `test_persistence_integration.py`) covering runs listing + run-scoped
  snapshot on the snapshot schema.

### B. All pages of all runs — kill the silent truncation
- Server-side pagination on `/api/live/snapshot` (`offset`/`page` +
  `limit`, total count returned) **or** raise the cap with streamed/chunked
  fetch — decide and document; either way the GUI must be able to reach
  every page of a large run, and must *show* when a view is partial
  (banner: "showing X of Y — load more/all").
- Per-run counts in the runs list must be correct on both schemas.

### C. Run-scoped truth on legacy DBs
- On the legacy (no-snapshot) schema, either scope queries to the selected
  run where the schema allows, or clearly label the view as "current state
  (not run-scoped)" in the UI and collapse the runs list to a single
  current-state entry — no more N identical runs each claiming every URL.

### D. Fill the stubbed fields where the DB has them
- Inlinks/outlinks from `internal_links` (counts + detail-pane lists),
  response time from `page_metadata` timings, structured data if stored.
  Anything genuinely absent stays empty — no fabrication.

## Definition of Done
- Bridge + tests are on master; `--check`-style CI coverage for the GUI node
  tests still green.
- Against a real multi-run site DB: every run appears once with correct
  counts; a >5k-page run is fully browsable via pagination/load-more and the
  partial-view state is visible whenever fewer pages than the total are shown.
- Legacy-schema DB: no run-scoping lie (scoped queries or an explicit
  current-state label).
- Detail pane shows real inlinks/outlinks and response times where the DB
  has them.

## Constraints
- Read-only: this ticket adds no write/submission endpoints (that is
  ticket 124, which depends on this landing first).
- Loopback only; one DSN per bridge process; no cross-database enumeration.
- Keep the sample-data fixture contract stable — prototype mode must not
  regress (fixture parity guard from ticket 118 stays green).

## Status
open (2026-07-17) — prerequisite for ticket 124.
