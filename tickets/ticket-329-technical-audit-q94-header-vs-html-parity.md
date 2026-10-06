# Ticket 329: Implement technical-audit Q94 — Header vs HTML parity

## Goal

Make Q94 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page's HTTP Link canonical or X-Robots-Tag disagree with its HTML canonical or meta robots?

## Rule

Issue if: At least one page has a header canonical different from its HTML canonical, or header and meta robots with conflicting index/follow values.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `canonical-declarations`, `indexability-segmentation`.
- New detector: none.
- Why it matters: When the header and the HTML disagree, Google may ignore both canonicals and applies the most restrictive robots directive, which can deindex a page by accident.

## Tasks

- [x] An explicit `Q94` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Add the Link-header canonical vs HTML canonical comparison; today only robots header/meta conflicts are tested.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q94 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] The answerer's `scope_note` is removed once the missing rule branches are tested.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P1**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
