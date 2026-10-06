# Ticket 314: Implement technical-audit Q56 — Semantic HTML5 & schema

## Goal

Make Q56 answerable from deterministic, run-scoped Python evidence.

## Question

Do article pages show a date with no <time datetime>, or a date that disagrees with datePublished/dateModified in structured data?

## Rule

Issue if: At least one article page's visible date differs from its schema date, or 20% of article pages have no <time datetime>.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Warning / Low.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `structured-data-feature-rules`.
- New detector: `date-consistency` (owned here; also used by [ticket 318]).
- Why it matters: Google chooses the date shown in results from several signals. When the visible date and the markup disagree it may show the wrong date or none.

## Tasks

- [ ] Implement detector `date-consistency`, then register an explicit `Q56` answerer.
- [ ] Reuse contract evidence from `structured-data-feature-rules`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q56 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
