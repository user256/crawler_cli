# Ticket 366: Implement technical-audit Q67 — Font performance & CWV

## Goal

Make Q67 answerable from deterministic, run-scoped Python evidence.

## Question

Does any @font-face rule lack font-display swap/optional, or does a page preload more than four font files?

## Rule

Issue if: At least one first-party @font-face has no font-display (or 'block'), or a page has > 4 font preloads.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `font-loading`.
- Why it matters: Without font-display, text stays invisible until the font loads, which delays the first render and can make LCP late.

## Tasks

- [ ] Implement detector `font-loading`, then register an explicit `Q67` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q67 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (partial); inline @font-face only (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages). External stylesheets are not fetched, so a clean result is Needs validation, never Healthy.
