# Ticket 362: Implement technical-audit Q63 — Server performance & security

## Goal

Make Q63 answerable from deterministic, run-scoped Python evidence.

## Question

Is the Strict-Transport-Security header missing or weak, the domain absent from the HSTS preload list, or OCSP stapling off?

## Rule

Issue if: HSTS max-age < 31536000 or missing includeSubDomains/preload, the preload list status is not 'preloaded', or the TLS handshake has no stapled OCSP response.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Improvement / Low.
- Required inputs: `probes`, `external-api`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `hsts-ocsp`.
- Why it matters: HSTS preload removes the first http-to-https redirect and prevents downgrade attacks; stapling shortens the TLS handshake. The search effect is small.

## Tasks

- [ ] Implement detector `hsts-ocsp`, then register an explicit `Q63` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q63 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `tls-probe` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet. Preload status needs hstspreload.org; missing preload/OCSP fields keep the answer below Healthy.
