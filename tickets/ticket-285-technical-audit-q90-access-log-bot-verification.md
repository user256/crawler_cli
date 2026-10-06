# Ticket 285: Implement technical-audit Q90 — Access-log bot verification

## Goal

Make Q90 answerable from deterministic, run-scoped Python evidence.

## Question

Do verified search-bot hits in the server logs show a crawl drop, repeated 4xx/5xx responses, or crawling concentrated on non-canonical URLs?

## Rule

Issue if: Supplied logs show any of: a week-on-week verified Googlebot hit drop over 30%, a URL with repeated 4xx/5xx to Googlebot, or over 20% of bot hits on non-canonical URLs.

## Evidence and reuse

- Group: `supplied-input` — answerable: With supplied data; ticket: on Issue when the input is supplied; otherwise Pending.
- Registry classification and priority: Issue / Medium.
- Required inputs: `logs`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `validated-bot-log-analysis`.
- New detector: none.
- Why it matters: Server logs are the only direct record of what Googlebot actually requests. They show crawl budget spent on errors and duplicates, and falling crawl rates that come before ranking drops.

## Tasks

- [ ] Implement an explicit `Q90` answerer over `validated-bot-log-analysis`.
- [ ] Reuse contract evidence from `validated-bot-log-analysis`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing input must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q90 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
