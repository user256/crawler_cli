# Ticket 303: Implement technical-audit Q32 — International

## Goal

Make Q32 answerable from deterministic, run-scoped Python evidence.

## Question

Is the main content of a locale page in a different language from its URL locale and html lang, or nearly identical to the default-language version?

## Rule

Issue if: At least one locale page's detected content language differs from its declared locale, or it is a near-duplicate of its default-language alternate.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Issue / Medium.
- Required inputs: `crawl`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `locale-html-lang`, `near-duplicate-content`.
- New detector: none.
- Why it matters: Untranslated locale pages are duplicates. Google may fold them into the original or treat them as low-quality, so the locale never ranks and the whole site looks thinner.
- Registry note: Language detection is statistical; confirm a sample before ticketing.

## Tasks

- [x] An explicit `Q32` answerer already exists in `technical_audit_questions.ANSWERERS`.
- [ ] Write regression tests: none reference `Q32` in `tests/test_technical_audit_questions.py` today. Cover a finding, a clean complete population, and unavailable or partial evidence.
- [ ] Confirm the answerer uses only its stated evidence population and never marks unavailable evidence Healthy.

## Definition of Done

- [ ] The runner produces the correct Q32 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; regression tests missing (Priority: **P2**).
