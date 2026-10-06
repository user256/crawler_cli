# Ticket 292: Implement technical-audit Q9 — International

## Goal

Make Q9 answerable from deterministic, run-scoped Python evidence.

## Question

Does any hreflang annotation lack a return link, or point at a URL that is not 200, is noindex, or canonicalises elsewhere?

## Rule

Issue if: At least one hreflang pair is not reciprocal, or its target is non-200, noindex or non-canonical.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `hreflang-html-http`, `hreflang-sitemap`, `hreflang-noindex`, `canonical-target-validation`.
- New detector: none.
- Why it matters: Google ignores hreflang pairs that do not point at each other or that target non-canonical or non-indexable URLs, so the wrong language version ranks in each market.

## Tasks

- [ ] Implement an explicit `Q9` answerer over `hreflang-html-http`, `hreflang-sitemap`, `hreflang-noindex`, `canonical-target-validation`.
- [ ] Reuse contract evidence from `hreflang-html-http`, `hreflang-sitemap`, `hreflang-noindex`, `canonical-target-validation`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q9 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
