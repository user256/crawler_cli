# Ticket 126: `initialize()` re-runs the legacy snapshot backfill, duplicating run data

## Goal
Stop `AsyncpgStore.initialize()` from mirroring already-run-scoped pages into a
phantom `legacy` snapshot run on databases that never had pre-095 data.

## Background — evidence (2026-07-17, found while building ticket 124)

`initialize()` backfills current-state rows into a one-time `legacy` snapshot
run so pre-095 installations do not lose data when readers became run-scoped
(`persistence.py:1276`, comment: *"Existing installations had only current-state
rows. Preserve a one-time `legacy` snapshot…"*). The intent is sound; the
trigger is not: it runs on **every** `initialize()`, guarded only by whether a
`legacy` snapshot already exists for that url_id — not by whether the database
was ever legacy.

Observed on a **fresh** database (no pre-095 data ever):

1. Bridge/CLI crawl #1 (`gui-…3c3d510f`) crawls 4 pages → 4 `page_run_snapshots`
   rows under that run, plus the usual current-state rows in `page_metadata`,
   `content`, `pages`.
2. Crawl #2 calls `initialize()` first. The backfill sees 4 `page_metadata` rows
   with no `legacy` snapshot and inserts them → a `legacy` run now holds a
   duplicate copy of crawl #1's 4 pages, with identical `fetched_at`.

```
            run_id             | snapshots
-------------------------------+-----------
 gui-20260717T114253Z-3c3d510f |         4
 gui-20260717T114332Z-661f089d |         2
 legacy                        |         4   <-- mirror of crawl #1
```

Consequences:
- **Storage:** the mirrored rows include `html_compressed`, so affected pages'
  snapshot HTML is stored twice.
- **Reporting/UI:** a phantom `legacy` run appears alongside real runs. The GUI
  (ticket 124) labels it *legacy (migrated current state)* so it is not mistaken
  for a crawl, but it should not exist on a never-legacy database at all.
- It is self-limiting (only pages lacking a `legacy` snapshot are inserted), so
  it does not grow without bound — but it doubles storage for every page crawled
  before the next `initialize()`.

## Tasks
- Gate the backfill on the database actually being legacy — e.g. run it only
  when `page_run_snapshots` is being created for the first time (pre-existing
  `page_metadata` rows but no snapshot table yet), or record a one-time
  migration marker in `crawl_metadata` and skip thereafter.
- Decide what to do about already-duplicated `legacy` rows on existing
  databases: leave them (historical), or offer a cleanup in `compact-crawl`.
  Do **not** silently delete run data as part of a migration.
- Consider whether `frontier`/`crawl_metadata`'s `'legacy'` defaults deserve the
  same marker treatment (they are cheap, so probably not).

## Definition of Done
- A fresh database crawled twice has **no** `legacy` snapshot run.
- A simulated pre-095 database (current-state rows, no `page_run_snapshots`)
  still gets its one-time `legacy` snapshot on first initialize, and does not
  re-backfill on the next initialize.
- Integration test covers both paths; suite/ruff/mypy green.

## Constraints
- Migration must stay idempotent and must not lose pre-095 data — that is the
  behaviour the original backfill exists to protect (ticket 095).
- No destructive cleanup without an explicit opt-in flag.

## Status
open (2026-07-17) — filed from the ticket-124 implementation.
