# Ticket 350: Implement technical-audit Q43 — Link equity & architecture

## Goal

Make Q43 answerable from deterministic, run-scoped Python evidence.

## Question

Do sitewide header or footer templates link to third-party or network sites outside the profile's allowed list, without nofollow?

## Rule

Issue if: At least one followed external link appears on over 50% of pages and its domain is not in the profile's allowed list.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `allowed_external_domains`.
- Threshold: `min_page_share = 0.5`.
- Existing contract checks: `external-link-integrity`.
- New detector: `sitewide-external-links`.
- Why it matters: Sitewide followed links between sister sites can look like a link network. They also add a link to every page that points visitors away from the site.

## Tasks

- [ ] Implement detector `sitewide-external-links`, then register an explicit `Q43` answerer.
- [ ] Reuse contract evidence from `external-link-integrity`.
- [ ] Read `allowed_external_domains` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q43 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; end-to-end from stored HTML (Priority: **P3**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Evidence: `technical-audit-observations --html-signals` (stored raw HTML). Verified on Rainbet run rainbet-20260925-v4 (10,852 pages). Needs `allowed_external_domains` in the site profile.
