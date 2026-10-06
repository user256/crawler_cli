# Ticket 361: Implement technical-audit Q29 — Performance

## Goal

Make Q29 answerable from deterministic, run-scoped Python evidence.

## Question

Do lab LCP, CLS or INP exceed Google's 'good' thresholds on a key template, or do in-content images lack width and height?

## Rule

Issue if: A template's p75 lab LCP > 2.5 s, CLS > 0.1 or INP > 200 ms, or over 20% of its images lack dimensions.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Warning / Medium.
- Required inputs: `render`.
- Threshold: `lcp_ms = 2500`, `cls = 0.1`, `inp_ms = 200`.
- Existing contract checks: `performance-distribution`, `image-markup`, `image-resource-delivery`.
- New detector: none.
- Why it matters: Core Web Vitals are part of page experience. Lab results show likely causes; field data (CrUX) decides whether it actually affects the site in search.
- Registry note: Lab only; confirm with CrUX or Search Console Core Web Vitals before ticketing.

## Tasks

- [ ] Implement an explicit `Q29` answerer over `performance-distribution`, `image-markup`, `image-resource-delivery`.
- [ ] Reuse contract evidence from `performance-distribution`, `image-markup`, `image-resource-delivery`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q29 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `render-trace` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
