# Ticket 330: Implement technical-audit Q24 — Crawl waste

## Goal

Make Q24 answerable from deterministic, run-scoped Python evidence.

## Question

Does any parameter URL family exceed its expected size, or grow between runs, while being crawlable and indexable?

## Rule

Issue if: A family is over 10% of crawled URLs or over its profile maximum, or grows over 20% from the previous run, and its URLs are crawlable and indexable.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `parameter_families`.
- Threshold: `min_share = 0.1`, `max_growth = 0.2`.
- Existing contract checks: `crawl-waste-url-families`, `parameter-and-faceted-controls`.
- New detector: none.
- Why it matters: Unbounded parameter families use crawl budget on duplicates and slow the crawling of real pages. A family that keeps growing means the problem gets worse with every crawl.
- Registry note: Without a profile, families are still sized and flagged at 10%; run-over-run growth needs a previous run ID.

## Tasks

- [ ] Implement an explicit `Q24` answerer over `crawl-waste-url-families`, `parameter-and-faceted-controls`.
- [ ] Reuse contract evidence from `crawl-waste-url-families`, `parameter-and-faceted-controls`.
- [ ] Read `parameter_families` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q24 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
