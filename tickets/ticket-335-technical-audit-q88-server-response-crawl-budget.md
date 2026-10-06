# Ticket 335: Implement technical-audit Q88 — Server response & crawl budget

## Goal

Make Q88 answerable from deterministic, run-scoped Python evidence.

## Question

Does any template have p90 server response time above 600 ms or p99 above 1.5 s?

## Rule

Issue if: At least one template with 20+ samples has p90 TTFB > 600 ms or p99 > 1,500 ms.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`.
- Threshold: `p90_ms = 600`, `p99_ms = 1500`, `min_samples = 20`.
- Existing contract checks: `performance-distribution`.
- New detector: none.
- Why it matters: Google lowers its crawl rate when the server is slow, so fewer pages get crawled. Slow TTFB also pushes LCP out of the 'good' range.
- Registry note: Measured from the crawler's location, not Google's.

## Tasks

- [ ] Implement an explicit `Q88` answerer over `performance-distribution`.
- [ ] Reuse contract evidence from `performance-distribution`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q88 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
