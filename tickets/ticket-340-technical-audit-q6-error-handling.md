# Ticket 340: Implement technical-audit Q6 — Error handling

## Goal

Make Q6 answerable from deterministic, run-scoped Python evidence.

## Question

Does a made-up URL under any main section return a status other than 404 or 410?

## Rule

Issue if: At least one synthetic non-existent URL returns 200 or redirects to a live page.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `soft404-error-routes`.
- New detector: none.
- Why it matters: If any URL returns 200, junk and mistyped URLs can be crawled and indexed indefinitely as soft 404s, and genuinely removed pages never drop out.

## Tasks

- [ ] Implement an explicit `Q6` answerer over `soft404-error-routes`.
- [ ] Reuse contract evidence from `soft404-error-routes`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q6 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
