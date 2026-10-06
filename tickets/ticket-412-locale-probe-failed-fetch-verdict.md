# Ticket 412: Do not turn failed language probes into confirmed locale issues

## Goal

Restore the evidence and coverage contract for Q25 after PR #118.

## Problem

A transport failure on one header variant becomes a confirmed site defect and an automatically generated ticket.

## Cause and evidence

`locale_probe_records` ignores outcome and skip_reason; `_initial_status` accepts internal status 0 as an HTTP status. `_locale_probe_changes` compares 200 to 0 and the complete collection is promoted to Issue.

The real Accept-Language collector runs against a deterministic engine fixture: baseline succeeds, Spanish request returns status 0 with no skip reason. It records outcome=fetch_error. Adapter plus runner produces Issue / Yes, ticket=true, finding `es-ES: status 200->0`.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `412` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [ ] Carry outcome and admission/fetch failure evidence into the adapter; 0 must not become an observed HTTP status.
- [ ] Treat unresolved comparisons as untested and retain successful variants without claiming complete coverage.
- [ ] Cover timeout, robots/scope rejection, failed redirect hop and true observed HTTP status changes separately; preserve valid findings while unknown-only comparisons produce no confirmed defect.

## Status

proposed (Priority: **P1**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 344, 386, 409. This records a fix request; no product fix has been applied.
