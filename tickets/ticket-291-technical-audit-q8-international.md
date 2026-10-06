# Ticket 291: Implement technical-audit Q8 — International

## Goal

Make Q8 answerable from deterministic, run-scoped Python evidence.

## Question

Is any page's <html lang> missing, invalid, or different from the language of its own self-referencing hreflang?

## Rule

Issue if: At least one page has no or an invalid html lang, or an html lang whose language differs from its self-hreflang code.

## Evidence and reuse

- Group: `crawl` — answerable: Yes; ticket: on Issue, at the entry's classification.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `locale-html-lang`, `hreflang-html-http`.
- New detector: none.
- Why it matters: Conflicting language signals make it unclear which locale a page targets. Google does not use html lang for targeting, but Bing and assistive tools do, and a mismatch almost always shows a template bug that also affects hreflang.

## Tasks

- [ ] Implement an explicit `Q8` answerer over `locale-html-lang`, `hreflang-html-http`.
- [ ] Reuse contract evidence from `locale-html-lang`, `hreflang-html-http`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs.

## Definition of Done

- [ ] The runner produces the correct Q8 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally (Stream B); QA-fixed, not merged (Priority: **P2**). Branch feature/technical-audit-stream-b; QA tickets 371-385.
