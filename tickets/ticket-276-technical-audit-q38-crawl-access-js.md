# Ticket 276: Implement technical-audit Q38 — Crawl access & JS

## Goal

Make Q38 answerable from deterministic, run-scoped Python evidence.

## Question

Do filter or category controls on listing templates change the listing without an <a href> to a distinct URL?

## Rule

Issue if: A filter or category control on a listing template is a button or scripted element with no crawlable href.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `render`, `site-profile`.
- Site-profile keys: `templates.listing`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `parameter-and-faceted-controls`, `rendered-robots-links`.
- New detector: `js-only-navigation-controls`.
- Why it matters: Category and useful filter states that exist only as JavaScript state have no URL, so they cannot be crawled, indexed or linked to. Search demand for those subsets goes to competitors.
- Registry note: Only filters with search demand need crawlable URLs; turning every facet into a link creates crawl waste (see Q24).

## Tasks

- [ ] Implement detector `js-only-navigation-controls`, then register an explicit `Q38` answerer.
- [ ] Reuse contract evidence from `parameter-and-faceted-controls`, `rendered-robots-links`.
- [ ] Read `templates.listing` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q38 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `listing-controls` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
