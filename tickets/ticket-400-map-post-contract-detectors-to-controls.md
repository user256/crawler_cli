# Ticket 400: Map the AI governance, Accept-Language and transport detectors to v3 controls

## Goal

Decide which v3 control each of the three detectors added after the control contract
(`ai-crawler-governance` from ticket 258, `transport-security` from 259,
`accept-language-variation` from 260) feeds, so their findings reach the client
contract instead of staying analyst-only.

## Problem

`feature/full-manual-review-audit` made `audit["checks"]` the fixed 44-control
contract projected by `project_v3_controls`; everything else is a detector in
`audit["detector_checks"]`. Tickets 258-260 landed on master after that branch
was cut and their tests looked for the new ids in `checks`. The reconciliation
merge (2026-10-06) keeps them as detectors and points the tests at
`detector_checks`; no control consumes them yet.

## Evidence

Merge of `feature/full-manual-review-audit` into origin/master: seven test
failures, all `StopIteration` on `audit["checks"]` lookups for these ids;
`CONTROL_DETECTORS` has no entry for them.

## Tasks

- [ ] Choose the control for each detector (candidates: `robots-controls` for AI governance, `locale-redirects` for Accept-Language, `nonproduction-https` for transport security) or add new controls with matching rows in `skills/technical-seo-audit/SKILL.md`.
- [ ] Update `CONTROL_DETECTORS`, `CONTROL_EVIDENCE_SCOPES` and, where a gap closes, `CONTROL_EVIDENCE_GAPS`.
- [ ] Extend the contract tests and the manual-review register expectations.

## Definition of Done

- [ ] Each of the three detectors is scoped to exactly one control, or deliberately documented as analyst-only.
- [ ] Full suite green.

## Status

proposed (Priority: **P2**). Source: master reconciliation, 2026-10-06.
