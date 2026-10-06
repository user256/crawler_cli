# Ticket 304: Implement technical-audit Q36 — URL consolidation

## Goal

Make Q36 answerable from deterministic, run-scoped Python evidence.

## Question

Are profile sub-tab URLs indexable and self-canonical instead of consolidated onto the main profile?

## Rule

Issue if: At least one URL matching the profile sub-tab pattern is 200, indexable and self-canonical.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `templates.profile_subtab`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `parameter-and-faceted-controls`, `indexability-segmentation`.
- New detector: `profile-subtab-indexability`.
- Why it matters: Each tab multiplies the number of thin, near-identical URLs per profile, which splits signals and uses crawl budget on pages that should not rank on their own.

## Tasks

- [ ] Implement detector `profile-subtab-indexability`, then register an explicit `Q36` answerer.
- [ ] Reuse contract evidence from `parameter-and-faceted-controls`, `indexability-segmentation`.
- [ ] Read `templates.profile_subtab` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q36 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
