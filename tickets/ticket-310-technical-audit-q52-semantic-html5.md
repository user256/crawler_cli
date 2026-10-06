# Ticket 310: Implement technical-audit Q52 — Semantic HTML5

## Goal

Make Q52 answerable from deterministic, run-scoped Python evidence.

## Question

Are comparison toplists or odds tables on the profile's comparison templates built from <div>s with no <table>?

## Rule

Issue if: A page on a profile comparison template contains the toplist selector with no <table> element inside it.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`, `site-profile`.
- Site-profile keys: `templates.comparison`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `table-markup`.
- Why it matters: Table markup is read as rows and columns of data, which makes comparison content easier to extract for featured snippets and AI answers.

## Tasks

- [ ] Implement detector `table-markup`, then register an explicit `Q52` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Read `templates.comparison` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q52 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
