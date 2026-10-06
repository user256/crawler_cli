# Ticket 348: Implement technical-audit Q39 — Internal linking

## Goal

Make Q39 answerable from deterministic, run-scoped Python evidence.

## Question

Does any link inside an H2 or H3 point at a redirecting, error or non-canonical URL?

## Rule

Issue if: At least one link whose xpath is within an h2/h3 has a non-200 or non-canonical target.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `internal-link-targets`.
- New detector: none.
- Why it matters: Section-heading links usually point to the most important related pages. When they redirect or break, the link that matters most on the page passes the least.
- Registry note: A subset of Q22 reported separately because it is usually a separate content fix.

## Tasks

- [x] An explicit `Q39` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the answer to redirecting and non-canonical heading links; today only 4xx/5xx targets are tested.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q39 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] The answerer's `scope_note` is removed once the missing rule branches are tested.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (partial); hand-off to Stream A (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Regression tests added (`test_q39_heading_links_scope_is_explicit`). Redirect and non-canonical heading targets remain untested: the `internal-link-targets` check keeps only `error_target` rows (and the report's CASE lets `empty_anchor` mask redirects). Extending that check belongs to Stream A ticket 343 (Q22); Q39 will pick it up through the same check and its scope_note can then be removed.

Update 2026-10-06: Stream B added a Q39 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
