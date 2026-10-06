# Ticket 365: Implement technical-audit Q66 — Image performance

## Goal

Make Q66 answerable from deterministic, run-scoped Python evidence.

## Question

Are content images served as JPEG or PNG instead of WebP or AVIF?

## Rule

Issue if: Over 20% of fetched in-content raster images have a JPEG/PNG content type.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `render`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `image-resource-delivery`.
- New detector: none.
- Why it matters: WebP and AVIF are usually 25–50% smaller, which speeds up LCP on image-heavy templates.
- Registry note: Compression quality is not measured.

## Tasks

- [ ] Implement an explicit `Q66` answerer over `image-resource-delivery`.
- [ ] Reuse contract evidence from `image-resource-delivery`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q66 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `image-resources` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
