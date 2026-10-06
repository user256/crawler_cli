# Ticket 320: Implement technical-audit Q62 — Anchor text optimization

## Goal

Make Q62 answerable from deterministic, run-scoped Python evidence.

## Question

Do internal links to review or commercial pages use generic anchor text without the entity name?

## Rule

Issue if: At least 20% of internal links to profile commercial templates use an anchor from the profile's generic phrase list.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `generic_anchor_phrases`, `templates.review`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `internal-authority`.
- New detector: `generic-anchor-text`.
- Why it matters: Anchor text tells Google what the target page is about. Generic labels such as 'Read review' waste that signal across thousands of links.

## Tasks

- [ ] Implement detector `generic-anchor-text`, then register an explicit `Q62` answerer.
- [ ] Reuse contract evidence from `internal-authority`.
- [ ] Read `generic_anchor_phrases`, `templates.review` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q62 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
