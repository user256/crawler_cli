# Ticket 369: Implement technical-audit Q86 — Critical rendering path

## Goal

Make Q86 answerable from deterministic, run-scoped Python evidence.

## Question

Does the <head> contain more than three render-blocking stylesheets or any synchronous external script?

## Rule

Issue if: A key template has > 3 blocking stylesheets or ≥ 1 external <script> in the head without async, defer or type=module.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `critical-resource-impact`.
- New detector: `render-blocking-head`.
- Why it matters: Everything that blocks rendering delays first paint for users and adds work for Google's renderer.

## Tasks

- [ ] Implement detector `render-blocking-head`, then register an explicit `Q86` answerer.
- [ ] Reuse contract evidence from `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q86 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages).
