# Ticket 297: Implement technical-audit Q16 — Structured data

## Goal

Make Q16 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page contain structured data that fails to parse, or duplicate entities with conflicting values?

## Rule

Issue if: At least one page has a JSON-LD/microdata parse error or conflicting duplicate entities.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `schema-parser-diagnostics`.
- New detector: none.
- Why it matters: Search engines ignore markup that does not parse, so the page loses the rich result or entity information the markup was added for.

## Tasks

- [x] An explicit `Q16` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q16 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; retain regression coverage (Priority: **P2**).
