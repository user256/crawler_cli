# Ticket 312: Implement technical-audit Q54 — Semantic HTML5 & images

## Goal

Make Q54 answerable from deterministic, run-scoped Python evidence.

## Question

Are most content images inside the main content without a <figure> and <figcaption>?

## Rule

Issue if: Over 50% of in-content images on content templates have no enclosing <figure> with a <figcaption>.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`.
- Threshold: `min_share = 0.5`.
- Existing contract checks: `image-markup`.
- New detector: `figure-markup`.
- Why it matters: Captions give image search extra context next to alt text. The effect is small and mostly on image search.

## Tasks

- [ ] Implement detector `figure-markup`, then register an explicit `Q54` answerer.
- [ ] Reuse contract evidence from `image-markup`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q54 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
