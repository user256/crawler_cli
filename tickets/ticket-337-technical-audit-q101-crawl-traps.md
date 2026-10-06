# Ticket 337: Implement technical-audit Q101 — Crawl traps

## Goal

Make Q101 answerable from deterministic, run-scoped Python evidence.

## Question

Does any discovered navigation-state family exceed its approved finite URL, date-range or traversal-depth limit?

## Rule

Issue if: A calendar, pagination, sort or filter family exceeds its documented URL-count, date-range or traversal-depth bound, or exposes a next-state link beyond that bound.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `crawl-waste-url-families`, `parameter-and-faceted-controls`.
- New detector: `bounded-navigation-states`.
- Why it matters: Unbounded navigation states can create near-duplicate URL populations that consume crawl capacity without adding useful indexable content.
- Registry note: Planned: no dedicated answerer yet. Requires approved finite limits for each family; a finite saved crawl cannot prove an infinite URL space. Report observed bound violations, qualify partial coverage and never traverse indefinitely.

## Tasks

- [ ] Implement detector `bounded-navigation-states`, then register an explicit `Q101` answerer.
- [ ] Reuse contract evidence from `crawl-waste-url-families`, `parameter-and-faceted-controls`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q101 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
