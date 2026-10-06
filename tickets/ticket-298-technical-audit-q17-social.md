# Ticket 298: Implement technical-audit Q17 — Social

## Goal

Make Q17 answerable from deterministic, run-scoped Python evidence.

## Question

Does any indexable page lack og:title, og:description, og:image or twitter:card, or reference an og:image that does not return 200?

## Rule

Issue if: At least 20% of indexable pages miss one of these tags, or any og:image returns non-200.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: none.
- New detector: `social-tags`.
- Why it matters: Social tags do not affect rankings. They control the preview when a page is shared in social apps, chat tools and some AI answers, which affects click-through from those channels.

## Tasks

- [ ] Implement detector `social-tags`, then register an explicit `Q17` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q17 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
