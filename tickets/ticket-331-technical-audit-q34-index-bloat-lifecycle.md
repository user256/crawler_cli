# Ticket 331: Implement technical-audit Q34 — Index bloat & lifecycle

## Goal

Make Q34 answerable from deterministic, run-scoped Python evidence.

## Question

Is any expired or ended lifecycle page 200 and indexable with no link to a live replacement, or still listed in a sitemap?

## Rule

Issue if: At least one URL matching the profile's expired markers is 200 + indexable without a link to a live equivalent, or is in a sitemap.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`, `site-profile`.
- Site-profile keys: `lifecycle`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `indexability-segmentation`.
- New detector: `lifecycle-pages`.
- Why it matters: Expired pages pile up into a large set of dead-end, low-value URLs. The fix depends on whether the page has links and demand: keep and link onward, 301, or 410.

## Tasks

- [ ] Implement detector `lifecycle-pages`, then register an explicit `Q34` answerer.
- [ ] Reuse contract evidence from `indexability-segmentation`.
- [ ] Read `lifecycle` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q34 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
