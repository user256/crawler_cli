# Ticket 305: Implement technical-audit Q37 — Indexability & thin content

## Goal

Make Q37 answerable from deterministic, run-scoped Python evidence.

## Question

Is any empty user profile indexable or listed in a sitemap?

## Rule

Issue if: At least one profile-template page meeting the profile's empty rule is indexable or in a sitemap.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`, `site-profile`.
- Site-profile keys: `templates.profile`, `empty_profile_rule`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `indexability-segmentation`, `content-quality`.
- New detector: `empty-profile-indexability`.
- Why it matters: Empty user profiles are thin pages in bulk, and they are a common target for spam sign-ups. Indexing them lowers perceived site quality.

## Tasks

- [ ] Implement detector `empty-profile-indexability`, then register an explicit `Q37` answerer.
- [ ] Reuse contract evidence from `indexability-segmentation`, `content-quality`.
- [ ] Read `templates.profile`, `empty_profile_rule` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q37 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
