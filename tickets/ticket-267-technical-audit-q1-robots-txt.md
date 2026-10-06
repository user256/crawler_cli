# Ticket 267: Implement technical-audit Q1 — Robots.txt

## Goal

Make Q1 answerable from deterministic, run-scoped Python evidence.

## Question

Does robots.txt block any URL the site needs crawled: an indexable page, a sitemap URL, an internally linked page, or a script, stylesheet or API resource that a page needs to render its copy?

## Rule

Issue if: At least one sitemap URL, internally linked HTML URL or render-critical resource has allowed_by_robots = false.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `robots`, `sitemaps`, `render`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`, `critical-resource-impact`.
- New detector: none.
- Why it matters: Google cannot crawl a blocked URL, so it cannot read or rank its content; a blocked page can still be indexed from links as a bare URL with no snippet. When a script or API that builds the page copy is blocked, Google renders the page without that copy.
- Registry note: Resource-level blocking needs a rendered crawl (--js); without it only HTML URLs are tested.

## Tasks

- [ ] Implement an explicit `Q1` answerer over `robots-controls`, `critical-resource-impact`.
- [ ] Reuse contract evidence from `robots-controls`, `critical-resource-impact`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q1 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
