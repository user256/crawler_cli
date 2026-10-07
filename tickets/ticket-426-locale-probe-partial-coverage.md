# Ticket 426: Mark the locale-probe collection partial when comparisons were not answered

## Problem

D2 in the ticket 419 live QA
([live-probe-run.md](./qa-new-audit-2026-10-06/live-probe-run.md)): both live
bundles marked the `locale-probe` collection `coverage_state: complete`, and
the persisted coverage row said `"complete": true`, while 21 of 28 records had
no answered status (14 `not_admitted`, 7 challenged).

Coverage was computed only from `len(targets) >= population`, in
`__main__._run_technical_audit_observations` and in the collector's coverage
row. Q25 compensated (24 untested, Needs validation), but every Q25 row carried
`"coverage": "complete"`, and any other consumer of the bundle or the stored
session saw a complete collection. That contradicts ticket 412's "retain
successful variants without claiming complete coverage".

## Tasks and acceptance criteria

- [x] The collector's coverage row is `complete` only when every eligible
      target was probed and every baseline, repeat and variant request was
      answered; it records the unanswered count and outcomes.
- [x] The bundle's `locale-probe` collection is `partial` whenever any
      comparison lacks an answered baseline or variant, and its scope says how
      many and why.
- [x] Q25 rows then carry `coverage: partial`, and a partial collection keeps
      a real finding below Issue.
- [x] Tests for both the bundle and the coverage row, plus a fully answered
      run that stays complete.

## Status

done (Priority: **P2**). Filed 2026-10-07 from the ticket 419 live QA (D2);
fixed on branch `fix/ticket-425-427`, 2026-10-07. Related: 412, 419, 425.

Fix: the collector's coverage row (also the stored `language_probe_sessions`
coverage) sets `complete` only when every eligible target was probed and no
probe was unanswered (`not_admitted`, `fetch_failed`, `fetch_error`, `challenged`,
`rate_limited` or `response_withheld`, on any hop, including the repeat control).
It adds `all_targets_probed`, `unanswered_probe_count` and
`unanswered_probe_outcomes`. `__main__._locale_probe_scope` makes the bundle's
`locale-probe` collection `partial` when targets were capped, any probe was
unanswered or any record has a baseline or variant failure, and the scope names the
counts (for example `1 probe requests unanswered (challenged 1)`). Q25 rows
then carry `coverage: partial`, and a real finding stays at Needs validation.
Tests in `tests/test_locale_probe_verdicts.py`: a run with one refused variant
(coverage row, scope and Q25 rows) and a fully answered run that stays complete
unless capped.
