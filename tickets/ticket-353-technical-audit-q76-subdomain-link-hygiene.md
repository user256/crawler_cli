# Ticket 353: Implement technical-audit Q76 — Subdomain & link hygiene

## Goal

Make Q76 answerable from deterministic, run-scoped Python evidence.

## Question

Do internal links point to staging, admin, preview or other non-canonical subdomains, or to hosts that don't resolve?

## Rule

Issue if: At least one link to a same-site subdomain other than the canonical host fails DNS or points at a non-production host.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `internal-link-targets`, `nonproduction-https`.
- New detector: none.
- Why it matters: Links to staging or admin hosts leak those hosts to crawlers and users. Links to dead subdomains are broken links.

## Tasks

- [ ] Implement an explicit `Q76` answerer over `internal-link-targets`, `nonproduction-https`.
- [ ] Reuse contract evidence from `internal-link-targets`, `nonproduction-https`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q76 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
