# Ticket 351: Implement technical-audit Q72 — Redirects & internal links

## Goal

Make Q72 answerable from deterministic, run-scoped Python evidence.

## Question

Does any internal link use the non-canonical trailing-slash form and cause a redirect?

## Rule

Issue if: At least one internal link differs from its final URL only by a trailing slash.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Low.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `internal-link-targets`, `url-host-and-variants`.
- New detector: none.
- Why it matters: Each such link costs an extra redirect for users and crawlers, and usually comes from one template or a menu setting.

## Tasks

- [ ] Implement an explicit `Q72` answerer over `internal-link-targets`, `url-host-and-variants`.
- [ ] Reuse contract evidence from `internal-link-targets`, `url-host-and-variants`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q72 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; focused regression coverage added (Priority: **P3**).

Update 2026-10-06: Stream B added a Q72 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
