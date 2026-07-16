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
