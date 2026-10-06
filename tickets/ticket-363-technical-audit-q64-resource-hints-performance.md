# Ticket 363: Implement technical-audit Q64 — Resource hints & performance

## Goal

Make Q64 answerable from deterministic, run-scoped Python evidence.

## Question

Does a page load render-critical fonts, CSS or its LCP image from a third-party origin without a preconnect hint?

## Rule

Issue if: A key template requests a render-blocking or LCP resource from another origin with no matching <link rel=preconnect>.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `render`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `critical-resource-impact`.
- New detector: `resource-hints`.
- Why it matters: Each new origin costs DNS, TCP and TLS round trips before the first byte. Preconnecting to the origins that block rendering shortens LCP.

## Tasks

- [ ] Implement detector `resource-hints`, then register an explicit `Q64` answerer.
- [ ] Reuse contract evidence from `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q64 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `render-trace` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
