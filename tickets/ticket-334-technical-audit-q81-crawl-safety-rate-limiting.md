# Ticket 334: Implement technical-audit Q81 — Crawl safety & rate limiting

## Goal

Make Q81 answerable from deterministic, run-scoped Python evidence.

## Question

Did the audit crawl trigger 429/503 rate limiting or measurable slowing of the origin?

## Rule

Issue if: The run recorded any 429/503, or response times rising over 50% during the run.

## Evidence and reuse

- Group: `run-gate` — answerable: Yes; ticket: never; a failure downgrades every other crawl answer to Needs validation.
- Registry classification and priority: none / none.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `audit-collection-safeguards`.
- New detector: none.
- Why it matters: This is about the audit crawler's own settings, not a site defect. Rate-limited responses do not show the site's normal behaviour, so affected rows are rechecked rather than ticketed.

## Tasks

- [ ] Implement an explicit `Q81` answerer over `audit-collection-safeguards`.
- [ ] Reuse contract evidence from `audit-collection-safeguards`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy or Pending under the run-gate contract; never infer Healthy from absent or incomplete evidence.
- [ ] Feed Q81 into the run gate alongside Q26 (`answer_questions` gates only on Q26 today), so a failure downgrades other crawl answers to Needs validation.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q81 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Never generate a client ticket; affected rows are rechecked, not ticketed.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; focused regression coverage added (Priority: **P2**).

Update 2026-10-06: Stream B added a Q81 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
