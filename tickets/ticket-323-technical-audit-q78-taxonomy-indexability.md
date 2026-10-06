# Ticket 323: Implement technical-audit Q78 — Taxonomy & indexability

## Goal

Make Q78 answerable from deterministic, run-scoped Python evidence.

## Question

Is any taxonomy archive that acts as a hub set to noindex?

## Rule

Issue if: At least one noindex tag, category or author URL is a profile hub or is in the top 10% of pages by internal inlinks.

## Evidence and reuse

- Group: `crawl+profile` — answerable: Yes, with site profile; ticket: on Issue; Pending when a profile key is missing.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`, `site-profile`.
- Site-profile keys: `templates.taxonomy`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `indexability-segmentation`, `internal-authority`.
- New detector: none.
- Why it matters: Noindexing a hub removes its own chance to rank, and over time Google also crawls its links less, so the pages beneath it lose discovery.

## Tasks

- [ ] Implement an explicit `Q78` answerer over `indexability-segmentation`, `internal-authority`.
- [ ] Reuse contract evidence from `indexability-segmentation`, `internal-authority`.
- [ ] Read `templates.taxonomy` from the site profile; return Pending when a required key is missing.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing profile key must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q78 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
