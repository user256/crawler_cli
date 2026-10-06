# Ticket 364: Implement technical-audit Q65 — Resource loading & priority

## Goal

Make Q65 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page preload an analytics or tag-manager script?

## Rule

Issue if: At least one <link rel=preload> points to a known analytics/tag-manager URL.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `tracking-preloads`.
- Why it matters: Preloading a tracking script gives it the same priority as the hero image and CSS, which delays what the user sees first.

## Tasks

- [ ] Implement detector `tracking-preloads`, then register an explicit `Q65` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q65 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages).
