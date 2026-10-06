# Ticket 294: Implement technical-audit Q11 — On-page

## Goal

Make Q11 answerable from deterministic, run-scoped Python evidence.

## Question

Do two or more indexable, self-canonical pages share the same title or the same H1?

## Rule

Issue if: At least one title or H1 value is shared by two or more indexable, self-canonical pages.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `metadata-duplicates-aliases`.
- New detector: none.
- Why it matters: Duplicate titles make pages compete for the same queries and lower click-through. They usually come from a template default that was never overridden.

## Tasks

- [ ] Implement an explicit `Q11` answerer over `metadata-duplicates-aliases`.
- [ ] Reuse contract evidence from `metadata-duplicates-aliases`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q11 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
