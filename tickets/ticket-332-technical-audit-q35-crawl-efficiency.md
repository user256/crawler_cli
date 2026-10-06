# Ticket 332: Implement technical-audit Q35 — Crawl efficiency

## Goal

Make Q35 answerable from deterministic, run-scoped Python evidence.

## Question

Does rendering a page issue more than 50 API (XHR/fetch) requests, or any uncacheable one?

## Rule

Issue if: A rendered page issues over 50 XHR/fetch requests, or an API response carries Cache-Control no-store/private.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Warning / Low.
- Required inputs: `render`.
- Threshold: `max_api_requests = 50`.
- Existing contract checks: `critical-resource-impact`.
- New detector: `render-api-requests`.
- Why it matters: Google's renderer fetches these requests too, from the same crawl budget. High request counts slow rendering and can cause timeouts that leave content out of the index.

## Tasks

- [ ] Implement detector `render-api-requests`, then register an explicit `Q35` answerer.
- [ ] Reuse contract evidence from `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q35 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `render-trace` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
