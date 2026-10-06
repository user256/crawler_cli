# Ticket 174: Document and lock DB-global `--refresh-days` semantics

## Goal
Make the already-intended DB-global periodic-refresh semantics explicit after
crawl-run isolation, and lock them with a multi-run regression.

## Background (2026-07-22 wiring audit)

Ticket **080** implemented freshness via `urls_fetched_since`, which joins
mutable `page_metadata` with **no** `run_id` (`persistence.py`). Tickets
**086** / **095** made frontier and reporting run-aware, but refresh still
treats “fetched recently in this database” as fresh for any new run.

A new run with `--refresh-days` can therefore skip an exact URL whose latest
successful fetch belongs to an older run. This initially looked like isolation
drift, but ticket **080** explicitly introduced the feature so periodic re-runs
within the window fetch approximately zero pages. A fresh run has no snapshots,
so changing freshness to active-run-only would largely disable the feature it
was created to provide.

## Decision

Keep freshness DB-global by exact normalized URL. Crawl-run isolation owns
frontier, snapshots, and reporting identity; `--refresh-days` is an opt-in cache
of the most recent successful fetch across those runs. Operators who require a
complete independent snapshot omit the flag (`0`, the default).

## Tasks
- Document the DB-global contract in CLI help + README with a two-run example,
  including how to force a complete independent run.
- Test two runs with overlapping exact URLs: the second run skips within the
  window and refetches with `--refresh-days 0` or after the cutoff.
- Confirm a URL is considered fresh only after a successful fetch and that
  unrelated URLs/runs do not cross-match.

## Definition of Done
- DB-global exact-URL behaviour is documented and covered by a multi-run test.
- Default `--refresh-days 0` still creates a complete independent run.

## Status
proposed (Priority: **P3**) — documentation/regression hardening; audit concern
resolved in favour of ticket 080's existing periodic-refresh contract.
