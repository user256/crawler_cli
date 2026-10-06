# Ticket 315: Implement technical-audit Q57 — SERP presentation & freshness

## Goal

Make Q57 answerable from deterministic, run-scoped Python evidence.

## Question

Does any commercial review or toplist title or H1 show a past year, or a month more than one month before the crawl?

## Rule

Issue if: At least one page on a profile commercial template has a year earlier than the crawl year (or a stale month) in its title or H1.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `templates.commercial`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `metadata-basics`.
- New detector: `stale-title-dates`.
- Why it matters: A past date in the title looks out of date in results and lowers click-through on queries where users expect current offers.
- Registry note: Adding the current month without actually updating the content is a known pattern Google may ignore; the date should reflect a real review.

## Tasks

- [ ] Implement detector `stale-title-dates`, then register an explicit `Q57` answerer.
- [ ] Reuse contract evidence from `metadata-basics`.
- [ ] Read `templates.commercial` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q57 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
