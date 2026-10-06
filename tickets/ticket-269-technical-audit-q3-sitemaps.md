# Ticket 269: Implement technical-audit Q3 — Sitemaps

## Goal

Make Q3 answerable from deterministic, run-scoped Python evidence.

## Question

Does any XML sitemap list a URL that does not return 200, is noindex, or canonicalises to a different URL?

## Rule

Issue if: At least one sitemap URL has status != 200, a noindex directive, or a canonical that is not itself.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `sitemap-integrity`, `canonical-target-validation`.
- New detector: none.
- Why it matters: A sitemap should list only the canonical, indexable version of each page. Redirects, errors, noindex and non-canonical entries waste crawl requests, send conflicting canonical signals and make Search Console's sitemap coverage report meaningless.

## Tasks

- [ ] Implement an explicit `Q3` answerer over `sitemap-integrity`, `canonical-target-validation`.
- [ ] Reuse contract evidence from `sitemap-integrity`, `canonical-target-validation`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q3 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
