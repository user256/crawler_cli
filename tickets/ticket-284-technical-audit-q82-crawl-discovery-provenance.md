# Ticket 284: Implement technical-audit Q82 — Crawl discovery provenance

## Goal

Make Q82 answerable from deterministic, run-scoped Python evidence.

## Question

Is any URL population found in one discovery source (sitemaps, internal links, supplied Search Console or backlink exports) but missing from the others?

## Rule

Issue if: At least one URL family is present in one source and absent from the internal link graph and the sitemaps.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `discovery-source-provenance`.
- New detector: none.
- Why it matters: URLs that Google or other sites know about but the site no longer links or lists are unmanaged: old, parameter or orphan URLs that still use crawl budget and can stay indexed.
- Registry note: Crawl and sitemap sources are always available; Search Console and backlink exports widen the comparison when supplied.

## Tasks

- [ ] Implement an explicit `Q82` answerer over `discovery-source-provenance`.
- [ ] Reuse contract evidence from `discovery-source-provenance`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q82 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; focused regression coverage added (Priority: **P2**).

Update 2026-10-06: Stream B added a Q82 answerer; QA fixes (tickets 383-385) on branch feature/technical-audit-stream-b make it usable. Remaining DoD items are Stream A's.
