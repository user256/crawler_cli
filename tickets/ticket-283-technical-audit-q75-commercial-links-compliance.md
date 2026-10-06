# Ticket 283: Implement technical-audit Q75 — Commercial links & compliance

## Goal

Make Q75 answerable from deterministic, run-scoped Python evidence.

## Question

Does any outbound affiliate link lack both rel="sponsored" (or nofollow) and routing through a robots-disallowed redirect path?

## Rule

Issue if: At least one link to a profile affiliate domain or path has neither a sponsored/nofollow rel nor a robots-disallowed /go/-style route.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Issue / High.
- Required inputs: `crawl`, `robots`, `site-profile`.
- Site-profile keys: `affiliate`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `external-link-integrity`, `robots-controls`.
- New detector: `affiliate-link-qualification`.
- Why it matters: Google requires paid and affiliate links to be qualified. Unqualified affiliate links can be treated as a link scheme, which risks a manual action and passes authority to partners.

## Tasks

- [ ] Implement detector `affiliate-link-qualification`, then register an explicit `Q75` answerer.
- [ ] Reuse contract evidence from `external-link-integrity`, `robots-controls`.
- [ ] Read `affiliate` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q75 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P1**).
