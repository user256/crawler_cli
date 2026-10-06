# Ticket 349: Implement technical-audit Q42 — Status codes & errors

## Goal

Make Q42 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page return 200 while showing an error or 'not found' message?

## Rule

Issue if: At least one 200 page has an error-page title/body signature or matches the site's 404 template.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `probes`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `soft404-error-routes`.
- New detector: none.
- Why it matters: Soft 404s are reported as errors in Search Console, waste crawl, and keep dead pages indexed.

## Tasks

- [ ] Implement an explicit `Q42` answerer over `soft404-error-routes`.
- [ ] Reuse contract evidence from `soft404-error-routes`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q42 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; focused regression coverage added (Priority: **P1**).

Update 2026-10-06: Stream B added a Q42 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
