# Ticket 302: Implement technical-audit Q30 — Search evidence

## Goal

Make Q30 answerable from deterministic, run-scoped Python evidence.

## Question

For any important template and locale, do Search Console records show important URLs not indexed, a Google-selected canonical different from the declared one, or indexed pages with no impressions?

## Rule

Issue if: Supplied Search Console data shows any of: important URLs excluded, Google canonical != declared canonical, or indexed URLs with zero impressions over 90 days.

## Evidence and reuse

- Group: `supplied-input` — answerable: With supplied data; ticket: on Issue when the input is supplied; otherwise Pending.
- Registry classification and priority: Issue / High.
- Required inputs: `gsc`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `supplied-search-evidence`.
- New detector: none.
- Why it matters: Only Search Console shows what Google actually did with the pages the crawl found: whether it indexed them, which canonical it chose and whether they earn impressions. Crawl findings are the likely causes; this is the result.

## Tasks

- [x] An explicit `Q30` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Write regression tests: none reference `Q30` in `tests/test_technical_audit_questions.py` today. Cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q30 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; retain regression coverage (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Regression tests added (`test_q30_supplied_search_evidence`): finding, clean, partial run and unavailable.
