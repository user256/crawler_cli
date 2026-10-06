# Ticket 306: Implement technical-audit Q41 — International & URL structure

## Goal

Make Q41 answerable from deterministic, run-scoped Python evidence.

## Question

Does any localized page sit outside its locale folder, or does a locale folder serve content in another language?

## Rule

Issue if: At least one page's declared language (html lang or self-hreflang) does not match its first path segment's locale.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `locale-html-lang`.
- New detector: `locale-path-consistency`.
- Why it matters: Mixed-language folders stop per-locale reporting in Search Console and make hreflang mapping and geotargeting error-prone.
- Registry note: A root-level default language is valid if it is consistent; the site profile can declare it.

## Tasks

- [ ] Implement detector `locale-path-consistency`, then register an explicit `Q41` answerer.
- [ ] Reuse contract evidence from `locale-html-lang`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q41 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
