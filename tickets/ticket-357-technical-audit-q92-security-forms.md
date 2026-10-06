# Ticket 357: Implement technical-audit Q92 — Security & forms

## Goal

Make Q92 answerable from deterministic, run-scoped Python evidence.

## Question

Does any form submit to an http:// URL?

## Rule

Issue if: At least one <form action> resolves to an http:// URL.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonproduction-https`.
- New detector: `insecure-form-actions`.
- Why it matters: Browsers warn users on insecure form submissions, and the data goes over an unencrypted connection. This is a security issue before it is an SEO one.

## Tasks

- [ ] Implement detector `insecure-form-actions`, then register an explicit `Q92` answerer.
- [ ] Reuse contract evidence from `nonproduction-https`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q92 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages).
