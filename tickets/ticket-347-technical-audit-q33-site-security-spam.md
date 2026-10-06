# Ticket 347: Implement technical-audit Q33 — Site security & spam

## Goal

Make Q33 answerable from deterministic, run-scoped Python evidence.

## Question

Does the site host user-generated spam, injected content or spam profiles?

## Rule

Issue if: At least one crawled page matches the spam pattern list (pharma, casino-spam, essay, crypto-scam terms or injected hidden links) outside the site's own topic.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Error / High.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `ugc-spam-patterns`.
- Why it matters: Hosted spam can trigger a manual action for user-generated spam or a site-reputation abuse action, and lowers trust in the whole domain.
- Registry note: A gambling site's own vocabulary overlaps spam lists; every match needs review.

## Tasks

- [ ] Implement detector `ugc-spam-patterns`, then register an explicit `Q33` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q33 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (heuristic, Needs validation at most) (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages).
