# Ticket 099: Crawl-run isolation (086) merge follow-ups

## Goal
Close the small, non-blocking issues found while reviewing and merging ticket
086 so run identity is clean end-to-end with no dead code or over-broad error
handling.

## Tasks
- Remove the no-op `--new-run` flag.
- Narrow run-selection errors so unrelated `RuntimeError`s still propagate.
- Remove dead legacy-run backfill SQL.
- Cover resume mismatch / not-found behavior with tests.

## Status
in progress (claimed 2026-07-15 on `agent/ticket-099-run-isolation-followups`)
