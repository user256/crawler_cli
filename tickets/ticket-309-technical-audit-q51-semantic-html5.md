# Ticket 309: Implement technical-audit Q51 — Semantic HTML5

## Goal

Make Q51 answerable from deterministic, run-scoped Python evidence.

## Question

Does any template's raw HTML lack a <main> element, or lack header and footer landmarks?

## Rule

Issue if: At least one template (by URL pattern) has no <main>, or neither <header> nor <footer>, in its raw HTML.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `semantic-landmarks`.
- Why it matters: Landmarks help parsers separate the main content from navigation and boilerplate. The search effect is small; the main benefit is accessibility and cleaner extraction by AI crawlers.

## Tasks

- [ ] Implement detector `semantic-landmarks`, then register an explicit `Q51` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q51 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
