# Ticket 092: Make persistence failures fail automation deterministically

## Goal
Prevent a crawl with lost database writes from exiting successfully by default.

## Background
`_persist_with_retry()` records `persist_error` on results after retries, and the
CLI prints the number of failures, but `_run_crawl()` leaves its exit code at
zero unless interrupted. CI, cron, or an API wrapper can therefore treat an
incomplete database crawl as successful.

## Tasks
- Define exit codes for complete success, partial persistence failure,
  interruption, validation error, and total crawl failure.
- Return a non-zero exit when any required page result failed to persist; offer
  an explicit best-effort override only if there is a real use case.
- Include failed URLs/counts in JSONL summary metadata and structured logs.
- Ensure a persisted fetch followed by frontier mark-done failure remains
  resumable rather than silently lost.
- Add CLI and engine tests for transient recovery, terminal persistence error,
  mixed success, save-to fallback, and exit-code precedence with interruption.

## Definition of Done
- Automation receives a non-zero status for incomplete persistence.
- The final summary states whether results are durable, partially durable, or
  available only in the saved output.

## Status
in_progress (Priority: **P1**) — claimed by `agent/ticket-092-persist-failure-exit-policy`; reliability/automation; found in 2026-07-15 audit.

