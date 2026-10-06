# Ticket 299: Implement technical-audit Q20 — Indexability

## Goal

Make Q20 answerable from deterministic, run-scoped Python evidence.

## Question

Is any noindex page on a template the site profile marks as indexable, listed in a sitemap, or linked from the main navigation?

## Rule

Issue if: At least one noindex URL matches an indexable profile template, appears in a sitemap, or is a navigation target.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `sitemaps`, `site-profile`.
- Site-profile keys: `templates`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `indexability-segmentation`.
- New detector: none.
- Why it matters: An unintended noindex removes the page from search completely. Noindex pages in sitemaps or navigation send contradictory signals and waste crawl.
- Registry note: Without a profile the noindex inventory by template is still produced, and the status is Needs validation.

## Tasks

- [ ] Implement an explicit `Q20` answerer over `indexability-segmentation`.
- [ ] Reuse contract evidence from `indexability-segmentation`.
- [ ] Read `templates` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q20 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P1**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
