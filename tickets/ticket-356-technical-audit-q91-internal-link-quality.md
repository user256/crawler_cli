# Ticket 356: Implement technical-audit Q91 — Internal link quality

## Goal

Make Q91 answerable from deterministic, run-scoped Python evidence.

## Question

Does any internal link have empty anchor text, with no alt text on a linked image either?

## Rule

Issue if: At least one internal <a> has empty or whitespace-only text and no image with non-empty alt.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `image-markup`.
- New detector: `empty-anchors`.
- Why it matters: An empty link gives Google no anchor text and screen readers nothing to announce. It is usually an icon or logo link without a label.

## Tasks

- [ ] Implement detector `empty-anchors`, then register an explicit `Q91` answerer.
- [ ] Reuse contract evidence from `image-markup`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q91 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
