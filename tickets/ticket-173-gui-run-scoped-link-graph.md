# Ticket 173: Run-scoped GUI in/outlink graph

## Goal
Show inlinks/outlinks for the selected crawl run, not the mutable global
`internal_links` table.

## Background (2026-07-22 wiring audit)

Ticket **125** filled GUI link fields from the DB. `_link_graph` still queries
`internal_links` with an explicit “current-state (latest crawl), not snapshot”
comment (`crawler_gui/server.py`). Snapshots already store `links_json`, but
the graph attach path ignores run scope.

After a second crawl of overlapping URLs, the run selector can show another
run’s edges (or a mix) while other panels are run-scoped.

GUI README already notes the limitation; this ticket closes it.

## Tasks
- Derive the graph from the selected run’s snapshot `links_json` (and/or a
  run-scoped edge source).
- Preserve honest behaviour on legacy schemas without snapshots.
- Test two runs, overlapping URLs, different discovered links.
- Update GUI README once behaviour matches.

## Definition of Done
- Link graph is scoped to the selected `run_id`.
- Legacy / missing-snapshot behaviour is documented and non-lying.
- Automated coverage for multi-run overlap.

## Status
proposed (Priority: **P2**) — GUI/persistence; found in 2026-07-22 audit.
