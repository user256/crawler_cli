# Ticket 355: Implement technical-audit Q79 — Server errors & 5xx stability

## Goal

Make Q79 answerable from deterministic, run-scoped Python evidence.

## Question

Does any URL return 5xx both in the crawl and on a live recheck?

## Rule

Issue if: At least one URL returns 5xx in the run and again on recheck.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `response-status-and-redirect-history`.
- New detector: none.
- Why it matters: Persistent 5xx errors make Google slow its crawl of the whole site and drop the affected pages from the index.
- Registry note: Qualification: recheck_required.

## Tasks

- [ ] Implement an explicit `Q79` answerer over `response-status-and-redirect-history`.
- [ ] Reuse contract evidence from `response-status-and-redirect-history`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q79 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
