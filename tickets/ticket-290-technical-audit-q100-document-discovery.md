# Ticket 290: Implement technical-audit Q100 — Document discovery

## Goal

Make Q100 answerable from deterministic, run-scoped Python evidence.

## Question

Does any document in the approved search inventory lack its designated crawlable HTML hub link or required sitemap entry?

## Rule

Issue if: An approved inventory document has no crawlable link from its designated HTML hub, or is marked for sitemap inclusion but is absent from its designated XML sitemap.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonhtml-search-assets`, `discovery-source-provenance`.
- New detector: `document-discovery-inventory`.
- Why it matters: Unlinked documents can be discovered inconsistently, while documents without a curated hub give users and crawlers little context about their purpose or relationship.
- Registry note: Planned: no dedicated answerer yet. Requires an approved document inventory naming each HTML hub, whether sitemap inclusion is required, and the designated sitemap. Incomplete HTML, document or sitemap coverage cannot establish a Healthy result.

## Tasks

- [ ] Implement detector `document-discovery-inventory`, then register an explicit `Q100` answerer.
- [ ] Reuse contract evidence from `nonhtml-search-assets`, `discovery-source-provenance`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q100 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
