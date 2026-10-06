# Ticket 293: Implement technical-audit Q10 — On-page

## Goal

Make Q10 answerable from deterministic, run-scoped Python evidence.

## Question

Does any page declare more than one title, meta description, canonical or meta robots tag?

## Rule

Issue if: At least one page has more than one of any of these elements in the raw HTML.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `metadata-basics`, `canonical-declarations`.
- New detector: none.
- Why it matters: With several canonicals Google may ignore them all; with several robots tags it applies the most restrictive one; with several titles it chooses one unpredictably. Each usually means two systems (theme and plugin) are writing the same tag.
- Registry note: Header-vs-HTML conflicts are Q94.

## Tasks

- [ ] Implement an explicit `Q10` answerer over `metadata-basics`, `canonical-declarations`.
- [ ] Reuse contract evidence from `metadata-basics`, `canonical-declarations`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q10 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P1**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
