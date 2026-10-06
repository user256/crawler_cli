# Ticket 272: Implement technical-audit Q14 — Internal linking

## Goal

Make Q14 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page carry more unique internal outlinks than the threshold?

## Rule

Issue if: At least one HTML page has more than 300 unique internal outlinks.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`.
- Threshold: `max_unique_internal_outlinks = 300`.
- Existing contract checks: `internal-authority`.
- New detector: `link-count-outliers`.
- Why it matters: Every extra link on a page divides the value passed to each target. Very high counts usually mean an oversized mega-menu or an unbounded link module, which flattens internal priority so key pages get no more weight than trivial ones.
- Registry note: High inlink counts are not a defect in themselves (the homepage and navigation targets always have them), so only outlinks are tested.

## Tasks

- [x] An explicit `Q14` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q14 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; retain regression coverage (Priority: **P3**).
