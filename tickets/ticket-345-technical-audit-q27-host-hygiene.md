# Ticket 345: Implement technical-audit Q27 — Host hygiene

## Goal

Make Q27 answerable from deterministic, run-scoped Python evidence.

## Question

Is any non-production or alternate host (staging, dev, preview, other brand hostnames) publicly reachable and indexable?

## Rule

Issue if: A host from the profile list, found in links, or found in certificate transparency logs returns 200 HTML without noindex or auth.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Error / High.
- Required inputs: `probes`, `site-profile`.
- Site-profile keys: `nonproduction_hosts`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `nonproduction-https`.
- New detector: none.
- Why it matters: Open staging and duplicate hosts can be indexed as copies of the live site, competing with it and exposing unreleased content.
- Registry note: Host discovery beyond the profile list and linked hosts (DNS or certificate-log enumeration) is an external step.

## Tasks

- [ ] Implement an explicit `Q27` answerer over `nonproduction-https`.
- [ ] Reuse contract evidence from `nonproduction-https`.
- [ ] Read `nonproduction_hosts` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q27 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; fed by exposure-inventory or host-probe records (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Exposure inventory reads headers only, so a reachable 200 host without X-Robots-Tag is a review candidate (Needs validation), not an Issue. Profile hosts not probed block a Healthy answer.
