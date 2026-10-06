# Ticket 333: Implement technical-audit Q70 — Robots.txt & crawl budget

## Goal

Make Q70 answerable from deterministic, run-scoped Python evidence.

## Question

Are internal search result or feed URLs found in the crawl, and allowed by robots.txt?

## Rule

Issue if: At least one discovered URL matching internal-search or feed patterns has allowed_by_robots = true.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `robots`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`, `crawl-waste-url-families`.
- New detector: none.
- Why it matters: Internal search creates unlimited low-value URLs, and Google recommends blocking it. Feeds are duplicates of pages that are already crawled.
- Registry note: Search and feed URL patterns can be overridden in the site profile.

## Tasks

- [ ] Implement an explicit `Q70` answerer over `robots-controls`, `crawl-waste-url-families`.
- [ ] Reuse contract evidence from `robots-controls`, `crawl-waste-url-families`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q70 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
