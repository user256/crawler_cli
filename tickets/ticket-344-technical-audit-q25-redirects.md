# Ticket 344: Implement technical-audit Q25 — Redirects

## Goal

Make Q25 answerable from deterministic, run-scoped Python evidence.

## Question

Does the site redirect or change content based on Accept-Language or the visitor's IP location?

## Rule

Issue if: The same URL gives a different status, Location or primary content when Accept-Language or egress country changes.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `locale-redirects`.
- New detector: none.
- Why it matters: Googlebot crawls mostly from the US without an Accept-Language header. Automatic locale redirects can hide every other locale version from Google.
- Registry note: Accept-Language needs no proxy; the IP part needs proxies for each tested country.

## Tasks

- [ ] Implement an explicit `Q25` answerer over `locale-redirects`.
- [ ] Reuse contract evidence from `locale-redirects`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q25 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `locale-probe` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet. Needs proxies per tested country for the IP part.
