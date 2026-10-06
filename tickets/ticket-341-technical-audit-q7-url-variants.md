# Ticket 341: Implement technical-audit Q7 — URL variants

## Goal

Make Q7 answerable from deterministic, run-scoped Python evidence.

## Question

Does an uppercase or camelCase variant of a URL return 200 without redirecting or canonicalising to the lowercase URL?

## Rule

Issue if: At least one case variant returns 200 with a self-referencing or missing canonical.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `url-host-and-variants`.
- New detector: none.
- Why it matters: URL paths are case-sensitive. Case variants that return 200 create duplicate URLs whenever someone links with the wrong case.

## Tasks

- [ ] Implement an explicit `Q7` answerer over `url-host-and-variants`.
- [ ] Reuse contract evidence from `url-host-and-variants`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q7 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
