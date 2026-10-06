# Ticket 274: Implement technical-audit Q23 — Internal linking

## Goal

Make Q23 answerable from deterministic, run-scoped Python evidence.

## Question

Are any inventory items (for example games) reachable only after clicking, scrolling or filtering, and absent from both the raw HTML and the initial render?

## Rule

Issue if: At least one inventory URL from the profile pattern appears only in the post-interaction link set.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `render`, `interaction`, `site-profile`.
- Site-profile keys: `templates.inventory`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `rendered-robots-links`.
- New detector: none.
- Why it matters: Google does not click, scroll or submit forms. Items that appear only after 'load more', a filter or infinite scroll are never discovered through links, and have to rely on the sitemap alone.

## Tasks

- [x] An explicit `Q23` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Write regression tests: none reference `Q23` in `tests/test_technical_audit_questions.py` today. Cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q23 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; regression tests missing (Priority: **P1**).
