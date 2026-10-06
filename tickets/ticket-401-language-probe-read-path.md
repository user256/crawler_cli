# Ticket 401: Decode persisted language-probe evidence and stop the placeholder posing as coverage

## Goal

Make ticket 264's persistence read path work against a real Postgres database.

## Problem

`latest_language_probe_evidence` did `dict(row["evidence_json"])`, but the pool is
created without a JSON codec, so asyncpg returns JSONB as text and the call raised
`ValueError`. Once any probe session existed for a run, every later
`technical-audit` for that run crashed, because the default report loop now fetches
the report. Separately, `CrawlReports.accept_language_probes` returned a
`record_type: "coverage"` placeholder when nothing was recorded, which the audit
read as a probe that ran, turning the detector `partial` instead of `unavailable`.

## Evidence

QA review of 55de4da, 2026-10-06. Every other JSONB read in persistence.py guards with
`json.loads(raw) if isinstance(raw, str)`.

## Tasks

- [x] Decode text JSONB in the read path (`_language_probe_evidence_row`).
- [x] Give the no-session placeholder a non-coverage `record_type`.
- [x] Regression tests with a fake pool and a no-session store.
- [ ] Extend the DSN-gated integration suite with a real round trip when a test database is available.

## Definition of Done

- [x] A persisted session reads back as decoded dicts.
- [x] An unprobed run keeps `accept-language-variation` unavailable with `requires_explicit_accept_language_probe`.

## Status

implemented (local) (Priority: **P1**). Source: master reconciliation QA, 2026-10-06.
