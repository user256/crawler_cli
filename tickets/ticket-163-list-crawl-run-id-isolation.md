# Ticket 163: List/CSV crawls must honour `--crawl-run-id`

## Goal
Make list/CSV crawls participate in crawl-run isolation the same way open
crawls do, so GUI List mode and CLI `--csv-file --crawl-run-id` write under the
requested run instead of silently landing in `legacy`.

## Background (2026-07-22 wiring audit)

Tickets **086** / **095** isolated open crawls by run. List mode was never
wired:

- `__main__._run_crawl` routes CSV list mode to `engine.crawl_list()` and never
  passes `run_id` (`__main__.py`).
- `crawl_list` / `crawl_many` never call `_prepare_crawl_run` /
  `set_active_crawl_run` (`engine.py`).
- Persist snapshots then use `store.active_run_id`, which defaults to
  `'legacy'` (`persistence.py`).
- The GUI still passes `--crawl-run-id` for List crawls and auto-loads that id
  (`crawler_gui/server.py` `build_crawl_argv`; app.js load-after-finish).

Result: a GUI List crawl “succeeds”, then the run selector finds an empty (or
wrong) run while pages collide under `legacy` across jobs.

## Tasks
- Give `crawl_list` an explicit `run_id` path and create/activate a crawl-run
  record before the first page persist. Honour an explicit flag; when omitted,
  generate a fresh id as open crawls do rather than falling back to `legacy`.
  GUI List mode already depends on the explicit path.
- Generalise the run-creation API so the record is stored with `mode='list'`;
  do not blindly reuse the current helper/API that hardcodes `mode='open'`.
- Carry the selected id through `CrawlJobResult.run_id`, saved output/summary,
  snapshots, run metadata, and reporting resolution.
- Apply an explicit list-run lifecycle: `running` on creation, a truthful
  completed/error/interrupted status on exit, and `failed` on an exception.
- Reject an already-existing explicit run id without overwriting it. List mode
  does not gain open-frontier resume semantics as part of this ticket.
- Add CLI/integration regressions for `--csv-file` + `--crawl-run-id`, including
  two list runs that contain the same URL but retain distinct snapshots.
- Manual/GUI check: List crawl appears under the returned `runId` with
  non-empty snapshots and is labelled List, not Spider.
- List-mode `--max-pages` semantics are intentionally handled by ticket **176**.

## Definition of Done
- An explicit `--crawl-run-id` never silently writes to `legacy`.
- A list crawl without the flag receives a generated non-legacy run id.
- GUI List crawl loads under the returned run id after finish, with `mode=list`
  and a terminal status rather than a stale `running` row.
- `CrawlJobResult` and saved job output expose the same run id.
- Reusing an existing run id fails clearly and cannot merge two list jobs.
- `--csv-file` + `--crawl-run-id` covered by an automated test.
- Open-crawl resume semantics unchanged.

## Status
proposed (Priority: **P0**) — data/crawl correctness; found in 2026-07-22 audit.
