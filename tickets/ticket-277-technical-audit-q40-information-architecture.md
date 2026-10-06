# Ticket 277: Implement technical-audit Q40 — Information architecture

## Goal

Make Q40 answerable from deterministic, run-scoped Python evidence.

## Question

Does the primary navigation in the raw HTML lack a direct <a href> to any commercial hub listed in the site profile?

## Rule

Issue if: At least one profile commercial hub has no <a href> inside the header or <nav> of the raw HTML of the homepage and main templates.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `stored-html`, `site-profile`.
- Site-profile keys: `commercial_hubs`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `nav-hub-links`.
- Why it matters: Navigation links appear on every page, so they pass the most internal authority and tell Google which pages matter most. A hub missing from the raw-HTML navigation depends on JavaScript or deep links to be found and ranked.

## Tasks

- [ ] Implement detector `nav-hub-links`, then register an explicit `Q40` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Read `commercial_hubs` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q40 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
