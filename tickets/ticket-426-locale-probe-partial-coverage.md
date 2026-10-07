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

- [ ] The collector's coverage row is `complete` only when every eligible
      target was probed and every baseline, repeat and variant request was
      answered; it records the unanswered count and outcomes.
- [ ] The bundle's `locale-probe` collection is `partial` whenever any
      comparison lacks an answered baseline or variant, and its scope says how
      many and why.
- [ ] Q25 rows then carry `coverage: partial`, and a partial collection keeps
      a real finding below Issue.
- [ ] Tests for both the bundle and the coverage row, plus a fully answered
      run that stays complete.

## Status

proposed (Priority: **P2**). Filed 2026-10-07 from the ticket 419 live QA (D2).
Related: 412, 419, 425.
