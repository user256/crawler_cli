# Ticket 316: Implement technical-audit Q58 — On-page & SERP features

## Goal

Make Q58 answerable from deterministic, run-scoped Python evidence.

## Question

Does any long-form page lack a table of contents of in-page links to its H2 sections?

## Rule

Issue if: At least 20% of pages with over 1,500 words and 4+ H2s have no set of #fragment links to their H2 ids.

## Evidence and reuse

- Group: `best-practice` — answerable: Yes; ticket: on Issue, classification capped at Improvement or Warning, priority at most Medium.
- Registry classification and priority: Improvement / Low.
- Required inputs: `crawl`, `stored-html`.
- Threshold: `min_share = 0.2`, `min_words = 1500`.
- Existing contract checks: none.
- New detector: `toc-presence`.
- Why it matters: In-page jump links help users and can appear as 'Jump to' links in search results.

## Tasks

- [ ] Implement detector `toc-presence`, then register an explicit `Q58` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q58 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Tickets are capped at Improvement or Warning classification and at most Medium priority.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P3**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
