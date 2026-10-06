# Ticket 326: Implement technical-audit Q84 — Structured data & rich results

## Goal

Make Q84 answerable from deterministic, run-scoped Python evidence.

## Question

Does any structured-data entity of a rich-result type miss a property Google requires?

## Rule

Issue if: At least one entity of a supported rich-result type lacks a required property under the documented rule set.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `structured-data-feature-rules`.
- New detector: none.
- Why it matters: An entity missing a required property is not eligible for its rich result, so the markup has no effect in search.

## Tasks

- [ ] Implement an explicit `Q84` answerer over `structured-data-feature-rules`.
- [ ] Reuse contract evidence from `structured-data-feature-rules`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q84 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
