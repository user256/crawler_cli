# Ticket 096: Raise and gate coverage of the PostgreSQL persistence layer

## Goal
Make the SQL-heavy persistence layer proportionally tested and ensure future
schema/frontier regressions fail CI.

## Background
The suite is healthy overall (367 passed, 13 skipped; 69% coverage), but
`persistence.py` has roughly 20% coverage in the standard coverage job despite
being the largest and highest-risk module. CI runs PostgreSQL integration tests
separately, but that job does not publish/merge coverage or enforce meaningful
persistence coverage. Ticket 066 added the integration foundation; this ticket
closes the remaining measurement and branch gaps.

## Tasks
- Collect coverage from the PostgreSQL integration job and combine it with unit
  coverage, or enforce a dedicated persistence/integration threshold.
- Cover schema initialization/migration, full result persistence, redirects,
  challenge outcomes, frontier claim/retry/resume isolation, deadlock retries,
  compaction/deletion safety, reports, and all run-scoped operations from 086/095.
- Add migration tests starting from representative older schemas, not only an
  empty database.
- Test transaction rollback/partial-failure invariants and concurrent claims.
- Publish an HTML/XML report artifact and raise the overall floor only after the
  critical branches are covered.

## Definition of Done
- PostgreSQL integration coverage contributes to a CI-enforced gate.
- Critical persistence/frontier migrations and failure paths have explicit tests.
- A regression in run isolation or write durability fails CI.

## Status
in_progress (Priority: **P2**) — claimed by `agent/ticket-096-persistence-coverage-gate`; test-risk follow-up to ticket 066; found in 2026-07-15 audit.

