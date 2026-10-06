# Ticket 327: Implement technical-audit Q85 — JavaScript & rendering parity

## Goal

Make Q85 answerable from deterministic, run-scoped Python evidence.

## Question

Does rendering change the canonical, title, meta robots or hreflang compared with the raw HTML?

## Rule

Issue if: At least one page's rendered value differs from its raw-HTML value for any of these elements.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `render`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `rendered-indexing-parity`.
- New detector: none.
- Why it matters: Google may use either version. A canonical or robots tag changed by JavaScript is unreliable, and a noindex in the raw HTML stops Google from rendering the page at all.

## Tasks

- [ ] Implement an explicit `Q85` answerer over `rendered-indexing-parity`.
- [ ] Reuse contract evidence from `rendered-indexing-parity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q85 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; fed by compare-renders (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `compare-renders --crawl-run-id RUN --output` passed to `technical-audit-observations --render-comparison`; a capped sample is partial coverage.
