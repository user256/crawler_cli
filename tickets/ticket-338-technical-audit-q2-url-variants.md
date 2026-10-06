# Ticket 338: Implement technical-audit Q2 — URL variants

## Goal

Make Q2 answerable from deterministic, run-scoped Python evidence.

## Question

Does any http/https or www/non-www variant fail to 301 or 308 to the canonical host in one hop?

## Rule

Issue if: At least one host or protocol variant returns 200, a non-permanent redirect, or a chain of more than one hop.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `url-host-and-variants`.
- New detector: none.
- Why it matters: Variants that do not redirect permanently split links and signals across duplicate copies of the site, and redirect chains slow crawling.

## Tasks

- [ ] Implement an explicit `Q2` answerer over `url-host-and-variants`.
- [ ] Reuse contract evidence from `url-host-and-variants`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q2 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
