# Ticket 328: Implement technical-audit Q87 — Non-HTML search assets

## Goal

Make Q87 answerable from deterministic, run-scoped Python evidence.

## Question

Is any non-HTML document indexable with neither a Link canonical header nor an X-Robots-Tag?

## Rule

Issue if: At least one linked PDF/DOC/XLS returns 200 with no X-Robots-Tag and no Link rel=canonical header.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonhtml-search-assets`.
- New detector: none.
- Why it matters: Without these headers, documents that duplicate an HTML page can outrank it, and documents that should stay private can be indexed.

## Tasks

- [ ] Implement an explicit `Q87` answerer over `nonhtml-search-assets`.
- [ ] Reuse contract evidence from `nonhtml-search-assets`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q87 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
