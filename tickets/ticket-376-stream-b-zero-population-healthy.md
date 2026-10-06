# Ticket 376: Never answer Healthy from a zero tested population

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Profile answerers for Q36, Q37 and Q78 return `denominator=0`, no rows and `complete=True` when no page matches the template, and the runner answers Healthy.

## Evidence

With a profile whose templates match no Rainbet URL, Q36, Q37 and Q78 answer Healthy with 0 pages tested.

## Tasks

- [x] Return Pending (unavailable, with the reason) when the template matches no saved page.
- [x] Add a runner-level guard: a matched=0/denominator=0 complete answer is never Healthy.
- [x] Add regression tests.

## Definition of Done

- [x] Q36/Q37/Q78 are Pending when their template matches nothing.
- [x] Existing Healthy answers with a real population are unchanged.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Profile answerers return Pending when the template matches no page; the runner never answers Healthy from a zero tested population.
