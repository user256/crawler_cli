# Ticket 318: Implement technical-audit Q60 — E-E-A-T & content freshness

## Goal

Make Q60 answerable from deterministic, run-scoped Python evidence.

## Question

Does any article page lack both a visible updated date and dateModified, or have dateModified earlier than datePublished?

## Rule

Issue if: At least one article page has no updated date in copy or markup, or dateModified < datePublished.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Warning / Low.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `structured-data-feature-rules`.
- New detector: `date-consistency` (built by ticket 314 for Q56; reuse it, do not rebuild).
- Why it matters: A clear last-updated date tells users and search engines the content is maintained, which matters for pages about offers and rules that change.

## Tasks

- [ ] Reuse detector `date-consistency` from ticket 314 (dependency), then register an explicit `Q60` answerer.
- [ ] Reuse contract evidence from `structured-data-feature-rules`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q60 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
