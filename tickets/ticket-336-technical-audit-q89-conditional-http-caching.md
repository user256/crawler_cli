# Ticket 336: Implement technical-audit Q89 — Conditional HTTP caching

## Goal

Make Q89 answerable from deterministic, run-scoped Python evidence.

## Question

Does the server ignore conditional requests, returning 200 instead of 304 for unchanged pages?

## Rule

Issue if: On a probe sample, pages that send ETag or Last-Modified return 200 to a matching conditional request, or send neither validator.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Improvement / Low.
- Required inputs: `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `conditional-cache-behaviour`.
- New detector: none.
- Why it matters: A 304 lets Googlebot skip downloading unchanged pages, which saves crawl capacity for pages that have changed.

## Tasks

- [ ] Implement an explicit `Q89` answerer over `conditional-cache-behaviour`.
- [ ] Reuse contract evidence from `conditional-cache-behaviour`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q89 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
