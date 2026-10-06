# Ticket 279: Implement technical-audit Q45 — International & internal linking

## Goal

Make Q45 answerable from deterministic, run-scoped Python evidence.

## Question

Do localized pages with hreflang alternates fail to link to their language siblings with a crawlable link?

## Rule

Issue if: At least 20% of pages with hreflang alternates have no <a href> to any of their alternates.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_share = 0.2`.
- Existing contract checks: `hreflang-html-http`.
- New detector: `locale-sibling-links`.
- Why it matters: Hreflang tags are not links. A crawlable language switcher lets users and crawlers move between editions and helps new locale pages get discovered.

## Tasks

- [ ] Implement detector `locale-sibling-links`, then register an explicit `Q45` answerer.
- [ ] Reuse contract evidence from `hreflang-html-http`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q45 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages). Rainbet: 10,441 of 10,639 pages with hreflang alternates have no sibling link (homepage spot-checked: 405 anchors, none to its 8 locale versions).
