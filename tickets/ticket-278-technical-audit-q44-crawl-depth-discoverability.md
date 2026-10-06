# Ticket 278: Implement technical-audit Q44 — Crawl depth & discoverability

## Goal

Make Q44 answerable from deterministic, run-scoped Python evidence.

## Question

Is any priority landing page more than three clicks from the homepage?

## Rule

Issue if: At least one URL matching the profile's priority templates or hub list has crawl depth > 3.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `commercial_hubs`, `templates.priority`.
- Threshold: `max_depth = 3`.
- Existing contract checks: `crawl-depth-distribution`.
- New detector: none.
- Why it matters: The further a page sits from the homepage, the less often it is crawled and the less internal authority it gets. A sitewide HTML sitemap or directory is one fix; the defect is the depth, not the missing sitemap.

## Tasks

- [ ] Implement an explicit `Q44` answerer over `crawl-depth-distribution`.
- [ ] Reuse contract evidence from `crawl-depth-distribution`.
- [ ] Read `commercial_hubs`, `templates.priority` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q44 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
