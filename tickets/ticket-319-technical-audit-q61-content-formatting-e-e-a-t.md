# Ticket 319: Implement technical-audit Q61 — Content formatting & E-E-A-T

## Goal

Make Q61 answerable from deterministic, run-scoped Python evidence.

## Question

Are quotations shown as styled paragraphs instead of <blockquote> with an attribution?

## Rule

Issue if: A sampled quotation on a content template is not inside <blockquote> or <q>, or has no cite or visible attribution.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `quotation-markup`.
- Why it matters: Marking quotations and their source makes attribution clear to users and to AI systems that cite content. The search effect is minor.
- Registry note: Quotations cannot be found reliably without markup, so this stays a manual sample.

## Tasks

- [ ] Implement detector `quotation-markup`, then register an explicit `Q61` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q61 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
