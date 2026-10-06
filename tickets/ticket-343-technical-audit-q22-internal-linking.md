# Ticket 343: Implement technical-audit Q22 — Internal linking

## Goal

Make Q22 answerable from deterministic, run-scoped Python evidence.

## Question

Does any internal link point at a URL that returns 4xx/5xx, redirects, is noindex, or canonicalises elsewhere?

## Rule

Issue if: At least one internal link target has one of these states.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `internal-link-targets`.
- New detector: none.
- Why it matters: Broken links waste crawl and frustrate users. Links to redirects, noindex or non-canonical URLs pass weaker signals and make Google crawl two URLs to reach one page.
- Registry note: Priority rises to High for 4xx/5xx targets linked from navigation.

## Tasks

- [x] An explicit `Q22` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the answer to redirecting, noindex and non-canonical link targets; today only 4xx/5xx targets are tested.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q22 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] The answerer's `scope_note` is removed once the missing rule branches are tested.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; focused regression coverage added (Priority: **P2**).

Update 2026-10-06: Stream B added a Q22 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
