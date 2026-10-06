# Ticket 325: Implement technical-audit Q83 — Hreflang & sitemaps

## Goal

Make Q83 answerable from deterministic, run-scoped Python evidence.

## Question

Do pages carry more than 20 hreflang alternates in the HTML head while no sitemap provides hreflang?

## Rule

Issue if: At least one page has over 20 head hreflang links and the sitemaps contain no xhtml:link annotations.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `sitemaps`.
- Threshold: `max_head_alternates = 20`.
- Existing contract checks: `hreflang-html-http`, `hreflang-sitemap`.
- New detector: none.
- Why it matters: Large hreflang sets in the head add weight to every page and are hard to keep reciprocal. Sitemaps keep them in one place. Both methods are valid; this is only worth changing at scale.

## Tasks

- [ ] Implement an explicit `Q83` answerer over `hreflang-html-http`, `hreflang-sitemap`.
- [ ] Reuse contract evidence from `hreflang-html-http`, `hreflang-sitemap`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q83 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P3**).
