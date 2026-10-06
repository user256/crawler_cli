# Ticket 296: Implement technical-audit Q15 — On-page

## Goal

Make Q15 answerable from deterministic, run-scoped Python evidence.

## Question

Does any indexable page have no H1, more than one H1, or skip a heading level (for example H2 to H4)?

## Rule

Issue if: At least one indexable page has zero or multiple H1s or a skipped heading level.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `metadata-basics`.
- New detector: `heading-sequence`.
- Why it matters: Headings give the page its outline. A missing H1 or broken hierarchy makes the main topic less clear to search engines and screen readers. The ranking effect is small; the fix is usually one template change.

## Tasks

- [ ] Implement detector `heading-sequence`, then register an explicit `Q15` answerer.
- [ ] Reuse contract evidence from `metadata-basics`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q15 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
