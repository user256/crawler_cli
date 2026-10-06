# Ticket 301: Implement technical-audit Q26 — Scope

## Goal

Make Q26 answerable from deterministic, run-scoped Python evidence.

## Question

Did the crawl end before its scope was covered, with more than 2% fetch failures, or with rate limiting?

## Rule

Issue if: The run stopped at a page/time limit, over 2% of fetches failed, or any 429/503 responses were recorded.

## Evidence and reuse

- Group: `run-gate` — answerable: Yes; ticket: never; a failure downgrades every other crawl answer to Needs validation.
- Registry classification and priority: none / none.
- Required inputs: `crawl`.
- Threshold: `max_failure_share = 0.02`.
- Existing contract checks: `audit-run-integrity`, `audit-collection-safeguards`.
- New detector: none.
- Why it matters: An incomplete crawl understates every count in the audit. This question never becomes a ticket; when it fails, every other crawl answer is reported as Needs validation.

## Tasks

- [x] An explicit `Q26` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q26 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Never generate a client ticket; affected rows are rechecked, not ticketed.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; retain regression coverage (Priority: **P2**).
