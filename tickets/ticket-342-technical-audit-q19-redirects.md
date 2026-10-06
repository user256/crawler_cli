# Ticket 342: Implement technical-audit Q19 — Redirects

## Goal

Make Q19 answerable from deterministic, run-scoped Python evidence.

## Question

Does any backlinked or legacy URL return an error, or redirect in a chain, instead of a single 301 to a relevant live page?

## Rule

Issue if: At least one supplied backlinked or archived URL returns 4xx/5xx or needs more than one redirect hop.

## Evidence and reuse

- Group: `supplied-input` — answerable: With supplied data; ticket: on Issue when the input is supplied; otherwise Pending.
- Registry classification and priority: Issue / High.
- Required inputs: `backlinks`, `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `response-status-and-redirect-history`.
- New detector: none.
- Why it matters: External links to dead URLs pass no value. Each one fixed with a single 301 recovers authority the site has already earned.
- Registry note: Needs a backlink export (Ahrefs/Semrush); archived URLs can come from the crawler's Wayback seeding.

## Tasks

- [ ] Implement an explicit `Q19` answerer over `response-status-and-redirect-history`.
- [ ] Reuse contract evidence from `response-status-and-redirect-history`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing input must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q19 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
