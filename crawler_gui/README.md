# crawler_gui — architecture & prototype

Static UI prototype and decision notes for an operator interface over crawl data.
See [PORTAL_MODULE.md](./PORTAL_MODULE.md) for the proposed self-hosted product
boundary, deployment shape, and API contract.

## Decision (2026-07-15)

**Build against `crawler_cli`, not `PostgreSQLCrawlerWIP`.**

| Piece | Role |
|---|---|
| **`crawler_cli`** | Product engine: schema, resume/delete, reports, CLI. Stay UI-free as a library. |
| **`crawler_api`** | Control plane: submit / status / results today; extend for list, resume, cancel, delete, config. |
| **PHP UI (new app)** | CrawlZilla-style shell: tables, overview, detail panes. Reads Postgres; calls `crawler_api` for jobs. |
| **`PostgreSQLCrawlerWIP`** | Legacy. Its Flask web UI is a useful reference (SQL browser + start/stop/resume), not the product UI. |

### Why not WIP?

- Ticket history treats WIP as an engine backport target, not the app shell.
- A new UI on WIP either freezes an obsolete stack or forever chases `crawler_cli`.
- Reuse WIP **ideas** (crawl-manager endpoints, rich SQL views); port missing views into `crawler_cli` when the UI needs them.

### Target shape

```
Browser (PHP UI)
  ├─ read  → Postgres (urls, page_metadata, indexability, internal_links, views…)
  └─ write → crawler_api → crawler_cli (crawl / resume / delete-crawl / config)
```

Do **not** have PHP spawn crawls directly if the API can own jobs (auth, isolation, concurrency).

Offline intent-overlap HTML (tickets 106/107) is complementary, not a substitute for this operator UI.

### MVP order

1. History + New Crawl / Options / Delete + live progress  
2. Internal URL table + Overview sidebar  
3. Bottom detail: URL details + inlinks/outlinks  
4. More category tabs (response codes, titles, canonicals, hreflang, …)  
5. Schedule last  

## Prototype in this folder

Static HTML fed by a generated JSON fixture so layout, colour, and interaction
can be iterated without PHP or Postgres.

| File | Purpose |
|---|---|
| `index.html` | Shell: nav, crawl bar, category tabs, grid, overview, detail, footer |
| `app.js` | Loads `sample-data.json`, renders tables/panels, handles selection/tabs/filter |
| `styles.css` | Light-first operator-tool chrome with an optional dark theme |
| `sample-data.json` | Fixture crawl (pages, overview, history, detail payloads) |
| `generate_sample_data.py` | Regenerates the JSON fixture |
| `intent-report-fixture.mjs` | Generated static fixture with the Ticket 106 `report_data.json` envelope |
| `intent-overlap.mjs` | The single adapter and dependency-free map/filter/table viewer for that envelope |
| `server.py` | Local read-only bridge serving the GUI against a live Postgres crawl database |

### Run the prototype

Serve this directory over HTTP (fetch needs a server; `file://` blocks JSON):

```bash
cd /home/user256/GitRepos/crawler_cli/crawler_gui
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

The grid shell loads `sample-data.json`, so it needs HTTP as above. The intent
overlap route (`index.html?view=intent-overlap`) does not fetch that JSON or any
third-party resource; it uses its imported static fixture instead.

Regenerate fixture:

```bash
python3 generate_sample_data.py
```

Verify that the checked-in fixture is exactly what the generator emits:

```bash
python3 generate_sample_data.py --check
```

## Live mode — `server.py` (ticket 125)

A local **read-only** bridge that serves this GUI against a real crawler_cli
PostgreSQL database instead of the fixture. One DSN per process; the local
convention is one database per site, so "all crawls" means every run of that
site.

```bash
python3 crawler_gui/server.py --postgres-dsn postgresql://user:pass@localhost:5432/sitedb
# or: export CRAWLER_CLI_POSTGRES_DSN=... ; python3 crawler_gui/server.py
# open http://127.0.0.1:8766/?live=1
```

| Endpoint | Purpose |
|---|---|
| `GET /api/live/runs` | Every crawl run in the database with per-run URL/HTML counts |
| `GET /api/live/snapshot?run=&limit=&offset=` | One page window of a run, plus whole-run overview/issues |
| `POST /api/live/crawls` | Start a crawl (ticket 124) — 202 with `{jobId, runId}` |
| `GET /api/live/crawls/{jobId}` | Job state, exit code, and a tail of its output |

URL params: `?live=1` enables live mode, `?run=<run_id>` selects a run (the URL
stays shareable), `?limit=<n>` sets the page-window size.

**Security posture:** binds `127.0.0.1` only, no auth. It is a development
bridge, not the `crawler_api` control plane — do not expose it.

## Managing crawls (ticket 124)

**Boundary decision.** This bridge was read-only by design, with crawl
submission reserved for `crawler_api`. Ticket 124 consciously relaxes that for
local-first use: submission runs here, over loopback. **Delete stays out** —
`delete-crawl` remains a CLI/API action, and there is no cancel. When
`crawler_api` owns jobs (auth, isolation, concurrency), submission should move
there.

- **Run selector.** In live mode the crawl bar shows a dropdown of every run in
  the database; picking one loads it in place and updates `?run=` so the URL
  stays shareable. History-modal cards switch runs the same way. (Previously the
  only way to change run was hand-editing the URL.)
- **New crawl.** The New Crawl modal submits to `POST /api/live/crawls`, which
  spawns `python -m crawler_cli crawl …` as a subprocess against the bridge's
  DSN — the real CLI, so robots/politeness/backends all apply. The status bar
  polls the job; on success the new run loads automatically, and on failure the
  tail of the crawler's own output is surfaced rather than the run vanishing.
- **One job at a time.** A second submission while one runs returns `409` naming
  the active job. Job records are in-memory: restarting the bridge forgets them
  (the crawl runs themselves are in Postgres and unaffected).
- **Config mapping.** Only fields with a real CLI flag are mapped
  (`maxPages`→`--max-pages`, `concurrency`→`--concurrency`,
  `respectRobots`→`--ignore-robots`, `userAgent`→`--custom-ua`, backend→
  `--http-backend`/`--js`). The Configuration modal's `delay` has no crawl-side
  CLI flag and is deliberately **not** invented.
- **List mode** needs a path to a local CSV file — `crawler_cli` does not ingest
  hosted URL lists, so a hosted list is rejected with that message.
- **Empty database.** A database with no crawls is a valid starting point: the
  GUI opens on an empty shell and New Crawl works. The bridge re-reads which
  tables exist per request, so a first crawl that creates the schema is picked
  up without a restart.

Values are passed as an argv list and spawned without a shell, so a crawl target
cannot inject a second command.

### Known upstream quirk — the `legacy` run

`AsyncpgStore.initialize()` backfills current-state rows into a one-time
`legacy` snapshot run so pre-095 data stays visible to run-scoped readers. It
re-runs on every init, so on a modern database the *next* crawl mirrors the
previous crawl's pages into a `legacy` run. The selector labels it
*legacy (migrated current state)* rather than hiding it, and hides it entirely
when it holds no pages. The duplication itself is engine behaviour, not the
bridge's.

### Behaviours worth knowing

- **Pagination, not truncation.** A window is `limit` pages (default 5000, max
  10 000) at `offset`. The toolbar always states `Showing X of Y URLs` and
  offers **Load more** until the run is fully loaded, so no page is
  unreachable and a partial view never reads as the whole run.
- **Whole-run overview.** The sidebar overview and issue counts come from a
  run-scoped SQL aggregate, not the loaded window, so they stay correct while
  paging.
- **Two schemas.** With `page_run_snapshots` (ticket 095) every run is listed
  and snapshots are genuinely run-scoped. On a legacy pre-095 database the page
  tables are global current state and cannot be attributed to a run, so the
  bridge collapses to a single `current-state` entry labelled
  *current state — not run-scoped* rather than listing N runs that each claim
  the whole database. The `legacy` compatibility placeholder run is hidden when
  it holds no pages.
- **Link graph.** Internal inlinks/outlinks (with anchor text) come from the
  current-state `internal_links` table on both schemas — it is not part of the
  immutable snapshot, so it reflects the most recent crawl. External outlinks
  come from a snapshot's `links_json` and only exist when the crawl ran with
  `same_host_only=False`; the default crawl drops cross-host links at
  extraction time, so they are genuinely absent rather than hidden.
- **No fabrication.** Fields the database does not hold stay empty — e.g.
  `responseTimeMs` is `null` when no fetch duration was recorded, rather than 0.

### Tests

```bash
pytest tests/test_crawler_gui_server.py            # pure mapping/aggregation, no DB
CRAWLER_CLI_TEST_DSN=postgresql://... pytest tests/test_persistence_integration.py \
  -k crawler_gui_bridge                            # run scoping, pagination, link graph
```

### JSON contract (prototype → future API)

Top-level keys the UI expects today:

- `crawl` — active crawl identity, mode, status, progress, speed  
- `history` — crawl slots for the History modal  
- `nav` / `categoryTabs` / `sidebarTabs` / `detailTabs` — chrome labels  
- `overview` — summary / responseCodes / content rows for the right rail  
- `pages[]` — grid rows; selected row drives the bottom detail panel  
  - nested `inlinks`, `outlinks`, `headers`, `structuredData`, on-page fields  

When `crawler_api` grows report endpoints, keep this shape (or map 1:1) so the
prototype can swap `sample-data.json` for `GET /crawls/{id}/ui-snapshot`.

### Intent Overlap / Cluster Report (Ticket 119)

The **Intent Overlap** primary-nav view is an additional, operator-facing
surface for Ticket 106 data. It is not an alternative implementation of the
analysis and it does not parse the CSV outputs: `intent-overlap.mjs` accepts
one `report_data.json`-shaped envelope containing the exported `pages`,
`pairs`, `clusters`, summary, thresholds, and projection coordinates.

The current prototype imports the generated `intent-report-fixture.mjs` rather
than making an API request. It includes a deliberately explicit completed-run
identity and points **Export HTML** at `./report.html`, the retained Ticket 107
portable/offline artifact. The static viewer makes no browser fetch/XHR calls
and has no third-party dependencies.

When Ticket 095 has established the run selector in the real control plane,
replace only the adapter input with a deterministic, run-scoped endpoint:

```
GET /crawls/{crawl_id}/runs/{run_id}/intent-report
```

The response must be the snapshot-backed Ticket 106 export for that exact
`run_id`, not current-state analysis rows. Continue to expose the corresponding
offline `report.html` artifact. The viewer already presents the selected run,
so it must not silently fall back to a latest/current run.

The view supports map hover/pin, wheel zoom and drag pan, URL search,
relation/page-type/risk filters, cluster selection, and synchronised
pages/pairs/clusters tables and detail. It uses the shell theme variables, so
the existing light/dark toggle applies to it too.

Validate its generated fixture and interaction model without installing any
browser packages:

```bash
python3 crawler_gui/generate_sample_data.py
node --test crawler_gui/test_intent_overlap.mjs
```

## Out of scope for this folder

- Real PHP server / auth / schedule persistence  
- Wiring to live Postgres or `crawler_api`  
- Exact competitor branding or feature parity (Lighthouse, Upgrade, etc.)
