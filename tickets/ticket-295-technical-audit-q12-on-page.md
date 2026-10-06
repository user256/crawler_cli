# Ticket 295: Implement technical-audit Q12 — On-page

## Goal

Make Q12 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page place a head-only element (title, meta robots, canonical, hreflang link) inside <body>?

## Rule

Issue if: At least one page has a head-only element parsed inside <body> of the raw HTML.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `head-elements-in-body`.
- Why it matters: Google stops reading the head at the first element that does not belong there. A canonical, robots or hreflang tag that ends up in the body is ignored.

## Tasks

- [ ] Implement detector `head-elements-in-body`, then register an explicit `Q12` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q12 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P1**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
