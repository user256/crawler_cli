# Ticket 115: Signal frontier mark-done / run incompleteness to automation

**Status:** done (2026-07-16, PR #37)
**Priority:** P2 reliability
**Related:** Ticket 092

## Goal

Make automation see incomplete crawl bookkeeping when a page persisted but
frontier mark-done failed, and stop labelling such runs as fully `complete`.

## Background

PR #25 (ticket 092) correctly exits non-zero on persist failures, surfaces
`durability`, and leaves persist-failed URLs pending for `--resume`. Two gaps
remain:

1. Successful persist + failed `frontier_mark_done` still yields exit `0` and
   `durability=durable` while the URL stays pending — data is durable, but
   frontier bookkeeping is incomplete and automation will not notice without
   log scraping.
2. Crawl-run status is still set to `"complete"` when persist failures leave
   pending rows (exit is non-zero, but the status string is optimistic).

## Tasks

- Treat mark-done failure after successful persist as an incomplete run state
  (non-zero exit and/or a distinct summary field); keep pending-for-resume
  behaviour.
- Avoid marking the crawl run `"complete"` when `persist_error_count > 0` or
  mark-done failures remain (e.g. `complete_with_errors` / resumable status);
  document the resume expectation.
- Add CLI/engine tests for mark-done failure signaling and status alignment.

## Definition of Done

Automation can detect frontier bookkeeping incompleteness without log
scraping; run status matches durability/resume reality; tests cover both
paths; ruff + mypy clean.
