# Ticket 313: Implement technical-audit Q55 — Semantic HTML5

## Goal

Make Q55 answerable from deterministic, run-scoped Python evidence.

## Question

Are repeated disclaimers and disclosures placed inside the main content rather than an <aside> or the footer?

## Rule

Issue if: On at least 20% of content pages, a profile disclaimer phrase appears inside <main>/<article> and outside any <aside>.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `stored-html`, `site-profile`.
- Site-profile keys: `disclaimer_phrases`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: none.
- New detector: `disclaimer-placement`.
- Why it matters: Repeated boilerplate inside the main content dilutes it and inflates near-duplicate similarity between pages. Marking it as an aside separates it from the page's real topic.

## Tasks

- [ ] Implement detector `disclaimer-placement`, then register an explicit `Q55` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Read `disclaimer_phrases` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q55 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
