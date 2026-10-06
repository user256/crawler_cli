# Ticket 286: Implement technical-audit Q93 — XML sitemap architecture

## Goal

Make Q93 answerable from deterministic, run-scoped Python evidence.

## Question

Does any XML sitemap fail to parse, exceed 50,000 URLs or 50MB uncompressed, or sit outside a sitemap index when the site has more than one sitemap?

## Rule

Issue if: At least one sitemap file is unparseable or over a protocol limit, or multiple sitemaps exist with no index referencing them.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `sitemap-integrity`.
- New detector: none.
- Why it matters: Search engines reject a sitemap file that breaks the protocol, so none of its URLs are read.
- Registry note: Gzip is optional in the sitemap protocol, so an uncompressed sitemap is not a defect.

## Tasks

- [ ] Implement an explicit `Q93` answerer over `sitemap-integrity`.
- [ ] Reuse contract evidence from `sitemap-integrity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q93 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
