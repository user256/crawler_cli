# Ticket 308: Implement technical-audit Q50 — Content quality & topical authority

## Goal

Make Q50 answerable from supplied, versioned evidence. The runner must not make live third-party requests.

## Question

Do leading competitors cover subtopics and entities of the core queries that the site does not?

## Rule

Issue if: An entity or SERP fan-out comparison finds subtopics covered by the top competitors and missing from the site.

## Evidence and reuse

- Group: `external` — answerable: No; ticket: never; always Pending with the tool needed.
- Registry classification and priority: Improvement / Medium.
- Required inputs: `external-api`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: none.
- Why it matters: Search and AI answers expand a query into related sub-questions. Sites that cover only the head topic lose the long tail and are cited less.

## Tasks

- [ ] Move Q50 from the `external` group to `supplied-input` in the registry first. While it is `external`, `_answer_one` returns Pending before looking up `ANSWERERS` (`technical_audit_questions.py`, the `group == "external"` branch), so a new answerer would be silently ignored.
- [ ] Implement a versioned supplied-evidence reader and an explicit `Q50` answerer; it must not make live third-party requests.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return Issue, Healthy, Needs validation or Pending only under the registry contract; never infer Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; a missing input must give Pending.

## Definition of Done

- [ ] The runner produces the correct Q50 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Keep the answer Pending until supplied evidence is present. The implementation may classify the supplied bundle but must not imply it queried Google or observed all SERPs.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

implemented locally; supplied input (competitor-topic-gap) (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Moved to `supplied-input`; Pending until a supplied bundle is attached.
