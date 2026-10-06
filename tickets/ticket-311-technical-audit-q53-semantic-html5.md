# Ticket 311: Implement technical-audit Q53 — Semantic HTML5

## Goal

Make Q53 answerable from deterministic, run-scoped Python evidence.

## Question

Are FAQ answers missing from the raw HTML (loaded only when clicked)?

## Rule

Issue if: At least one page has an FAQ answer (from FAQPage markup or accordion selectors) whose text is absent from its raw HTML.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `rendered-indexing-parity`.
- New detector: `faq-answer-presence`.
- Why it matters: Content that loads only on click is not indexed. Hidden-but-present content (CSS-collapsed or <details>) is indexed normally.
- Registry note: Using <details>/<summary> is good practice but not required; the defect is answers absent from the HTML.

## Tasks

- [ ] Implement detector `faq-answer-presence`, then register an explicit `Q53` answerer.
- [ ] Reuse contract evidence from `rendered-indexing-parity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q53 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
