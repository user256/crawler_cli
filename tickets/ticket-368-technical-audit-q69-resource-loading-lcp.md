# Ticket 368: Implement technical-audit Q69 — Resource loading & LCP

## Goal

Make Q69 answerable from deterministic, run-scoped Python evidence.

## Question

Is the LCP element on any key template a CSS background image?

## Rule

Issue if: On a key template the rendered LCP element's image comes from a CSS background-image.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Improvement / Low.
- Required inputs: `render`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `critical-resource-impact`.
- New detector: `lcp-background-image`.
- Why it matters: Browsers find CSS background images late and cannot prioritise them, and they are not indexed as images.

## Tasks

- [ ] Implement detector `lcp-background-image`, then register an explicit `Q69` answerer.
- [ ] Reuse contract evidence from `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q69 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `render-trace` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
