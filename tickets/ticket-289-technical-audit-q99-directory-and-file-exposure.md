# Ticket 289: Implement technical-audit Q99 — Directory and file exposure

## Goal

Make Q99 answerable from deterministic, run-scoped Python evidence.

## Question

Does any tested document, upload or asset directory expose an unintended generated file listing?

## Rule

Issue if: A scoped directory probe returns a generated file listing that exposes file or child-directory links and is not an approved public directory.

## Evidence and reuse

- Group: `heuristic` — answerable: Partly; ticket: never automatic; status is at most Needs validation until a person confirms.
- Registry classification and priority: Warning / Medium.
- Required inputs: `crawl`, `stored-html`, `probes`, `site-profile`.
- Threshold: `min_affected = 1`.
- Existing contract checks: none.
- New detector: `directory-listing-exposure`.
- Why it matters: Browsable directory listings can expose unpublished files, create low-value crawl paths and allow documents to be enumerated outside an intentional content journey.
- Registry note: Planned: no dedicated answerer yet. Listing fingerprints are candidates for manual confirmation against approved directories. Only scoped directory responses are tested; disabling listings does not prove that sensitive files cannot be fetched directly. Public document discovery belongs to Q100.

## Tasks

- [ ] Implement detector `directory-listing-exposure`, then register an explicit `Q99` answerer.
- [ ] Define and persist the minimum evidence schema before classifying.
- [ ] Emit run-scoped evidence rows with URL or host identity, observed value, rule, source check and coverage/qualification.
- [ ] Return at most Needs validation (or Pending when inputs are missing); never Issue, and never Healthy from absent or incomplete evidence.
- [ ] Add focused fixtures for finding, clean complete, partial and unavailable inputs; prove no automatic client ticket is raised.

## Definition of Done

- [ ] The runner produces the correct Q99 answer and status for complete, partial and unavailable evidence.
- [ ] Every affected item is traceable to retained evidence; denominators and coverage limitations are explicit.
- [ ] Cap the answer at Needs validation and do not generate an automatic client ticket.
- [ ] Regenerate the review document when the registry contract changes; preserve the question's Yes = problem polarity.

## Status

proposed (Priority: **P2**).
