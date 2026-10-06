# Ticket 268: Implement technical-audit Q97 — Robots.txt

## Goal

Make Q97 answerable from deterministic, run-scoped Python evidence.

## Question

Does any discovered URL fail its approved crawl, noindex or authentication policy?

## Rule

Issue if: A URL designated for crawl blocking is allowed by robots.txt; a public URL designated for noindex lacks the directive or is Disallowed; or a protected path exposes its content without authentication.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `robots`, `probes`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `robots-controls`, `indexability-segmentation`.
- New detector: `unwanted-path-policy`.
- Why it matters: Uncontrolled search, account, preview and other low-value URL paths can waste crawl capacity and expose pages not intended for discovery. robots.txt alone does not prevent a linked URL appearing in search.
- Registry note: Planned: no dedicated answerer yet. Requires an approved per-path policy, with distinct crawl-block, public-noindex and authentication routes. A saved crawl cannot establish undiscovered paths or live authentication; missing inputs remain Pending.

## Tasks

- [ ] Implement detector `unwanted-path-policy`, then register an explicit `Q97` answerer.
- [ ] Reuse contract evidence from `robots-controls`, `indexability-segmentation`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q97 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
