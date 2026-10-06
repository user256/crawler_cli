# Ticket 270: Implement technical-audit Q4 — Sitemaps

## Goal

Make Q4 answerable from deterministic, run-scoped Python evidence.

## Question

Is any indexable, self-canonical page that returns 200 in the crawl missing from every XML sitemap?

## Rule

Issue if: At least one crawled 200, indexable, self-canonical HTML URL is absent from all discovered sitemaps.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `sitemap-integrity`, `discovery-source-provenance`.
- New detector: none.
- Why it matters: The sitemap is Google's list of pages the site wants indexed. Pages left out are found only through links, so they are discovered and recrawled more slowly, which matters most for new and deep pages.

## Tasks

- [ ] Implement an explicit `Q4` answerer over `sitemap-integrity`, `discovery-source-provenance`.
- [ ] Reuse contract evidence from `sitemap-integrity`, `discovery-source-provenance`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q4 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
