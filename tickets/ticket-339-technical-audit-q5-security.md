# Ticket 339: Implement technical-audit Q5 — Security

## Goal

Make Q5 answerable from deterministic, run-scoped Python evidence.

## Question

Does any HTTPS page load an http:// resource, or link internally to an http:// URL?

## Rule

Issue if: At least one HTTPS page references an http:// image, script, stylesheet or iframe, or has an internal http:// link.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonproduction-https`.
- New detector: `mixed-content`.
- Why it matters: Browsers block insecure scripts and flag insecure images, which breaks pages and removes the secure padlock. Internal http:// links add a redirect hop to every click and crawl.

## Tasks

- [ ] Implement detector `mixed-content`, then register an explicit `Q5` answerer.
- [ ] Reuse contract evidence from `nonproduction-https`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q5 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages).
