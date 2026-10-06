# Ticket 281: Implement technical-audit Q48 — Information architecture

## Goal

Make Q48 answerable from deterministic, run-scoped Python evidence.

## Question

Does any guide or sub-category page lack a link to its parent hub or to at least one peer hub?

## Rule

Issue if: At least 20% of pages on the guide template link neither to their profile parent hub nor to a peer hub.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `templates.guide`, `hub_clusters`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `internal-authority`.
- New detector: `hub-cluster-links`.
- Why it matters: Links between a guide, its parent and its peers show Google the topic cluster and move authority to the hub pages that target the head terms.

## Tasks

- [ ] Implement detector `hub-cluster-links`, then register an explicit `Q48` answerer.
- [ ] Reuse contract evidence from `internal-authority`.
- [ ] Read `templates.guide`, `hub_clusters` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q48 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
