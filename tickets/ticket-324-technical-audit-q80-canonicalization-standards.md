# Ticket 324: Implement technical-audit Q80 — Canonicalization standards

## Goal

Make Q80 answerable from deterministic, run-scoped Python evidence.

## Question

Does any canonical tag use a relative URL?

## Rule

Issue if: At least one canonical declaration lacks a scheme and host.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `canonical-declarations`.
- New detector: none.
- Why it matters: Relative canonicals resolve against whatever host served the page, so staging mirrors, http variants and proxies all declare themselves canonical.

## Tasks

- [ ] Implement an explicit `Q80` answerer over `canonical-declarations`.
- [ ] Reuse contract evidence from `canonical-declarations`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q80 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
