# Ticket 288: Implement technical-audit Q98 — Robots.txt

## Goal

Make Q98 answerable from deterministic, run-scoped Python evidence.

## Question

Does a host's robots.txt fail its approved availability, syntax, sitemap-declaration or broad-rule policy?

## Rule

Issue if: For a host required to publish robots.txt, the response is not a usable 200 file, a recognised directive is malformed, an approved sitemap declaration is missing or a broad Disallow rule violates the approved policy.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `robots`, `sitemaps`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`, `sitemap-integrity`.
- New detector: `robots-file-policy`.
- Why it matters: An unavailable, malformed or over-broad robots.txt file can stop intended crawling and hide the sitemap routes that guide controlled discovery.
- Registry note: Planned: no dedicated answerer yet. Needs raw robots response/body and approved host rules and sitemap declarations. Absence of robots.txt or of a Sitemap directive is not inherently a crawl failure; report policy non-compliance separately from observed blocking.

## Tasks

- [ ] Implement detector `robots-file-policy`, then register an explicit `Q98` answerer.
- [ ] Reuse contract evidence from `robots-controls`, `sitemap-integrity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q98 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
