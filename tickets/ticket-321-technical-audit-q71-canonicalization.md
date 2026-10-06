# Ticket 321: Implement technical-audit Q71 — Canonicalization

## Goal

Make Q71 answerable from deterministic, run-scoped Python evidence.

## Question

Is any indexable 200 HTML page missing a canonical (HTML link or HTTP header)?

## Rule

Issue if: At least one 200, indexable HTML page has neither a <link rel=canonical> nor a Link canonical header.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `canonical-declarations`.
- New detector: none.
- Why it matters: Without a declared canonical, Google picks one itself among parameter, case and trailing-slash variants, and may choose the wrong URL.

## Tasks

- [ ] Implement an explicit `Q71` answerer over `canonical-declarations`.
- [ ] Reuse contract evidence from `canonical-declarations`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q71 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
