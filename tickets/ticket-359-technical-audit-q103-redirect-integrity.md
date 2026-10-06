# Ticket 359: Implement technical-audit Q103 — Redirect integrity

## Goal

Make Q103 answerable from deterministic, run-scoped Python evidence.

## Question

Does any internal, sitemap or approved legacy URL violate its direct-destination or permanent-redirect policy?

## Rule

Issue if: An internal or sitemap URL redirects; or an approved legacy redirect loops, takes more than one hop, uses a temporary response where a permanent move is required, or fails to reach its approved canonical destination.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`, `probes`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `response-status-and-redirect-history`, `internal-link-targets`.
- New detector: `redirect-policy-integrity`.
- Why it matters: Redirect chains and loops waste crawl capacity, delay users and weaken consolidation signals to the intended canonical URL.
- Registry note: Planned: no dedicated answerer yet. Needs full redirect histories, internal and sitemap membership, and approved legacy targets. Temporary redirects are not inherently defects; evaluate the approved intent. Missing history or incomplete populations remain Pending or qualified.

## Tasks

- [ ] Implement detector `redirect-policy-integrity`, then register an explicit `Q103` answerer.
- [ ] Reuse contract evidence from `response-status-and-redirect-history`, `internal-link-targets`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q103 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
