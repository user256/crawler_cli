# Ticket 287: Implement technical-audit Q95 — Mobile & interstitial compliance

## Goal

Make Q95 answerable from deterministic, run-scoped Python evidence.

## Question

On a mobile render, does an overlay cover most of the viewport on load, or remove the primary content from the rendered DOM?

## Rule

Issue if: A mobile render of a key template shows an overlay covering over 50% of the viewport, or rendered primary-content word count drops below 50% of the raw HTML.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Warning / Medium.
- Required inputs: `mobile-render`.
- Threshold: `min_affected = 1`.
- Existing contract checks: `mobile-rendering-parity`.
- New detector: `interstitial-coverage`.
- Why it matters: Intrusive interstitials count against page experience on mobile, and a gate that removes the content from the DOM stops it being indexed at all.
- Registry note: Legally required cookie and age gates are allowed if they are reasonably sized and the content remains in the DOM.

## Tasks

- [ ] Implement detector `interstitial-coverage`, then register an explicit `Q95` answerer.
- [ ] Reuse contract evidence from `mobile-rendering-parity`.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q95 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

answerer implemented; collector missing (Priority: **P2**).

Stream C commit 84f80f5 on branch feature/technical-audit-stream-c. Answerer in `technical_audit_observed_answers.py`; tests in `tests/test_technical_audit_observed_answers.py` cover finding, clean complete, partial, unavailable and missing-field evidence. Collector missing: the answer stays Pending until a `mobile-render` observation collection is attached (format in docs/technical-audit-observations.md). No crawler_cli command produces it yet.
