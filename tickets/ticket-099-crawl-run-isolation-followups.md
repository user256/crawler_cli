# Ticket 099: Crawl-run isolation (086) merge follow-ups

**Status:** done (2026-07-15, PR #20). Leftover optional hygiene → ticket 112.
**Priority:** P2

## Goal
Close the small, non-blocking issues found while reviewing and merging ticket
086 so run identity is clean end-to-end with no dead code or over-broad error
handling.

## Tasks
- Remove the no-op `--new-run` flag.
- Narrow run-selection errors so unrelated `RuntimeError`s still propagate.
- Remove dead legacy-run backfill SQL.
- Cover resume mismatch / not-found behavior with tests.

## Done
Shipped in PR #20: `CrawlRunSelectionError`, `--new-run` removed, dead
legacy-run backfill SQL dropped, resume mismatch/not-found (+ override warn)
and “unrelated RuntimeError still propagates” tests added. Optional 090/091
hygiene deferred to ticket 112.
