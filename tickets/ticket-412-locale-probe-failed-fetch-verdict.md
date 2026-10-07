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

- [x] Carry outcome and admission/fetch failure evidence into the adapter; 0 must not become an observed HTTP status.
- [x] Treat unresolved comparisons as untested and retain successful variants without claiming complete coverage.
- [x] Cover timeout, robots/scope rejection, failed redirect hop and true observed HTTP status changes separately; preserve valid findings while unknown-only comparisons produce no confirmed defect.

## Status

done (Priority: **P1**). Fixed on branch `fix/postmerge-qa-locale`, 2026-10-07.

Fix: `locale_probe_records` now only accepts real HTTP statuses (100-599); an unanswered request (status 0) gives
`variant_status`/`baseline_status` None, Location keys are recorded only when both first requests were answered, and
each record carries `baseline_outcome`/`variant_outcome` plus `baseline_failure`/`variant_failure` (outcome, skip
reason, failing hop). The Q25 answerer also rejects status 0 from older saved bundles, counts such probes as untested
and names the failure reasons in its note, so resolved variants stay tested but Q25 cannot reach Issue or Healthy from
them (Needs validation / No (partial), no ticket; Pending when nothing could be compared). The collector's
`differences_from_no_header` no longer reports `first_status_changed`/`final_status_changed` against an unanswered hop,
so a failed fetch no longer raises a `missing_vary_header` candidate. A language redirect whose target is then refused
keeps its real 200->302 + Location finding. Regression tests: `tests/test_locale_probe_verdicts.py` (no-reason fetch
error, timeout, robots and scope rejection, unanswered baseline, all variants failing, failed redirect hop, real 404
change, legacy status-0 record).

Note: the collector still labels an engine timeout (status 0 with `skip_reason="fetch_error:..."`) as outcome
`not_admitted`; the skip reason is carried through, and changing the outcome label would alter the bot-trap
classification, so it was left as is.
