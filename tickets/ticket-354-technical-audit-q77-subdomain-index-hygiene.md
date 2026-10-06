# Ticket 354: Implement technical-audit Q77 — Subdomain & index hygiene

## Goal

Make Q77 answerable from deterministic, run-scoped Python evidence.

## Question

Are cache, CDN, image-resizer or preview hosts serving indexable HTML copies of pages?

## Rule

Issue if: At least one profile cache/preview host or path returns 200 HTML without noindex, a canonical to the main host, or a robots block.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `probes`, `site-profile`.
- Site-profile keys: `nonproduction_hosts`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonproduction-https`, `robots-controls`.
- New detector: none.
- Why it matters: HTML copies on cache or preview hosts are duplicates of the site and can be indexed instead of it.
- Registry note: Image-resizer paths that serve images (not HTML) should stay crawlable, or image search breaks; do not block /_next/image in robots.txt.

## Tasks

- [ ] Implement an explicit `Q77` answerer over `nonproduction-https`, `robots-controls`.
- [ ] Reuse contract evidence from `nonproduction-https`, `robots-controls`.
- [ ] Read `nonproduction_hosts` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q77 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; fed by exposure-inventory or host-probe records (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Mitigations (noindex, canonical to main host, robots block) must be recorded per host; unread mitigations make the row a review candidate.
