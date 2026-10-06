# Ticket 280: Implement technical-audit Q46 — DOM completeness & rendering

## Goal

Make Q46 answerable from deterministic, run-scoped Python evidence.

## Question

On article templates, are footer navigation links missing from the raw HTML and present only after rendering or scrolling?

## Rule

Issue if: At least one article-template page has footer links in the rendered DOM that are absent from its raw HTML.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`, `render`, `stored-html`, `site-profile`.
- Site-profile keys: `templates.article`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `rendered-indexing-parity`.
- New detector: `footer-link-parity`.
- Why it matters: Links added only after rendering or scrolling are invisible to raw-HTML crawlers and may never be seen by Google's renderer, so the sitewide footer stops passing authority from article pages.

## Tasks

- [ ] Implement detector `footer-link-parity`, then register an explicit `Q46` answerer.
- [ ] Reuse contract evidence from `rendered-indexing-parity`.
- [ ] Read `templates.article` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q46 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `render-parity` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet. compare-renders does not record footer link inventories (`footer.raw_links`/`footer.rendered_links`).
