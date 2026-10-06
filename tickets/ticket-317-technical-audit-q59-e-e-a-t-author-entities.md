# Ticket 317: Implement technical-audit Q59 — E-E-A-T & author entities

## Goal

Make Q59 answerable from deterministic, run-scoped Python evidence.

## Question

Does any review or affiliate article lack a visible author byline linked to an author page, or author markup?

## Rule

Issue if: At least one page on a profile review template has no linked byline and no author property in its Article/Review markup.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `crawl`, `stored-html`, `site-profile`.
- Site-profile keys: `templates.review`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `structured-data-feature-rules`.
- New detector: `author-bylines`.
- Why it matters: Gambling is a Your Money or Your Life topic. Google's quality guidelines look for who wrote and checked the content, and anonymous reviews rank poorly in these results.

## Tasks

- [ ] Implement detector `author-bylines`, then register an explicit `Q59` answerer.
- [ ] Reuse contract evidence from `structured-data-feature-rules`.
- [ ] Read `templates.review` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q59 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
