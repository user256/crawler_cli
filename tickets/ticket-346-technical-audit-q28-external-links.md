# Ticket 346: Implement technical-audit Q28 — External links

## Goal

Make Q28 answerable from deterministic, run-scoped Python evidence.

## Question

Does any outbound link return 4xx/5xx, or does a paid/affiliate outbound link lack rel=sponsored or nofollow?

## Rule

Issue if: On an external recheck, at least one outbound link returns 4xx/5xx, or a profile affiliate link lacks the rel qualification.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `external-link-integrity`.
- New detector: none.
- Why it matters: Broken outbound links reflect poor maintenance on review pages. Unqualified paid links break Google's link-scheme policy (see Q75).
- Registry note: The external recheck runs at a slow, conservative rate.

## Tasks

- [ ] Implement an explicit `Q28` answerer over `external-link-integrity`.
- [ ] Reuse contract evidence from `external-link-integrity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q28 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `external-link-recheck` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
