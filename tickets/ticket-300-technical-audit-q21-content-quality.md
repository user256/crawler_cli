# Ticket 300: Implement technical-audit Q21 — Content quality

## Goal

Make Q21 answerable from deterministic, run-scoped Python evidence.

## Question

Are inventory pages (for example games) thin or near-duplicates of each other?

## Rule

Issue if: At least 10% of inventory-template pages have fewer than 250 main-content words or belong to a near-duplicate cluster.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `templates.inventory`.
- Threshold: `min_share = 0.1`, `min_words = 250`.
- Existing contract checks: `content-quality`, `near-duplicate-content`.
- New detector: none.
- Why it matters: Large sets of thin or templated pages lower Google's view of site quality overall and are commonly 'Crawled, currently not indexed'. They also compete with each other for the same queries.

## Tasks

- [x] An explicit `Q21` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Add the thin-content word-count test; today only near-duplicates are answered.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q21 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] The answerer's `scope_note` is removed once the missing rule branches are tested.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (partial); scope gaps remain (Priority: **P2**).
