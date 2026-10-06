# Ticket 282: Implement technical-audit Q49 — Internal linking & clusters

## Goal

Make Q49 answerable from deterministic, run-scoped Python evidence.

## Question

Do news and article pages lack an in-body link to any commercial or guide hub?

## Rule

Issue if: At least 20% of article-template pages have no in-body <a href> to a profile commercial hub.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `crawl`, `stored-html`, `site-profile`.
- Site-profile keys: `templates.article`, `commercial_hubs`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `internal-authority`.
- New detector: `article-to-hub-links`.
- Why it matters: News and articles attract most external links and fresh crawls. Without links to the commercial hubs, that authority stays on short-lived articles instead of reaching the pages that earn revenue.

## Tasks

- [ ] Implement detector `article-to-hub-links`, then register an explicit `Q49` answerer.
- [ ] Reuse contract evidence from `internal-authority`.
- [ ] Read `templates.article`, `commercial_hubs` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q49 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
