# Ticket 352: Implement technical-audit Q74 — Asset accessibility

## Goal

Make Q74 answerable from deterministic, run-scoped Python evidence.

## Question

Does any internally referenced image, video, script or stylesheet return 403 or another 4xx?

## Rule

Issue if: At least one first-party asset referenced by a crawled page returns 4xx.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`, `render`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `image-resource-delivery`, `critical-resource-impact`.
- New detector: none.
- Why it matters: Missing images and scripts break pages for visitors, and a render resource that returns an error leaves Google with an incomplete page.

## Tasks

- [ ] Implement an explicit `Q74` answerer over `image-resource-delivery`, `critical-resource-impact`.
- [ ] Reuse contract evidence from `image-resource-delivery`, `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q74 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
