# Ticket 273: Implement technical-audit Q18 — Crawl access

## Goal

Make Q18 answerable from supplied, versioned evidence. The runner must not make live third-party requests.

## Question

Does Google's own smartphone renderer, from a Google IP, fail to render the primary content of key templates?

## Rule

Issue if: URL Inspection or the Rich Results Test shows missing primary content, blocked resources or a render error for a key template.

## Evidence and reuse

- Group: `external` — answerable: No; ticket: never; always Pending with the tool needed.
- Registry classification and priority: Error / High.
- Required inputs: `external-api`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `mobile-rendering-parity`.
- New detector: none.
- Why it matters: If Google's renderer is blocked, geo-gated or times out, the indexed version of the page lacks its content, and nothing else in the audit will show it.
- Registry note: A US mobile Playwright render (mobile-rendering-parity) is supporting evidence only; confirmation needs URL Inspection.

## Tasks

- [ ] Move Q18 from the `external` group to `supplied-input` in the registry first. While it is `external`, `_answer_one` returns Pending before looking up `ANSWERERS` (`technical_audit_questions.py`, the `group == "external"` branch), so a new answerer would be silently ignored.
- [ ] Implement a versioned supplied-evidence reader and an explicit `Q18` answerer; it must not make live third-party requests.
- [ ] Reuse contract evidence from `mobile-rendering-parity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing input must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q18 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Keep the answer Pending until supplied evidence is present. The implementation may classify the supplied bundle but must not imply it queried Google or observed all SERPs.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; supplied input (google-render-inspection) (Priority: **P1**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Moved to `supplied-input`; Pending until a supplied bundle is attached; the runner never queries Google.
