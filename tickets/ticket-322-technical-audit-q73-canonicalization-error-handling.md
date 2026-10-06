# Ticket 322: Implement technical-audit Q73 — Canonicalization & error handling

## Goal

Make Q73 answerable from deterministic, run-scoped Python evidence.

## Question

Does any non-homepage URL canonicalise to the homepage?

## Rule

Issue if: At least one URL other than the homepage and its variants declares the homepage as its canonical.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `canonical-target-validation`, `soft404-error-routes`.
- New detector: none.
- Why it matters: Google treats a canonical to the homepage from unrelated pages as a soft 404 and ignores it. Retired pages should return 404/410 or 301 to a relevant replacement.

## Tasks

- [ ] Implement an explicit `Q73` answerer over `canonical-target-validation`, `soft404-error-routes`.
- [ ] Reuse contract evidence from `canonical-target-validation`, `soft404-error-routes`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q73 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P1**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
