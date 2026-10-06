# Ticket 271: Implement technical-audit Q13 — Internal linking

## Goal

Make Q13 answerable from deterministic, run-scoped Python evidence.

## Question

Does any indexable sitemap URL receive no internal link from any crawled page?

## Rule

Issue if: At least one indexable sitemap URL has zero run-scoped internal inlinks.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `orphan-candidates`.
- New detector: none.
- Why it matters: Pages with no internal links receive no internal authority and are crawled less often. Google treats them as unimportant, so they rarely rank even when the content is good.
- Registry note: Pages linked only from areas the crawl could not reach (login, robots-blocked) can appear here.

## Tasks

- [x] An explicit `Q13` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Extend the existing regression tests to cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q13 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; retain regression coverage (Priority: **P1**).
