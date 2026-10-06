# Ticket 384: Finish the Q81 run gate that Stream B started

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Stream B added Q81 as a second run gate using the saved 429/503 count. The question also asks whether response times rose over 50% during the run, which is not tested, yet a zero count answers Healthy. Audits saved before `rate_limited_count` existed now fail the gate, downgrading every answer.

## Evidence

Q81 Healthy is reachable without the timing test; Stream C fixtures without the count fail the gate.

## Tasks

- [x] Add the response-time drift test from saved `fetched_at`/`ttfb_seconds`, or keep Q81 below Healthy with a scope note until it exists.
- [x] Document that older audits fail the gate until regenerated.
- [x] Hand to Stream A ticket 334 (Q81) / 301 (Q26).

## Definition of Done

- [x] Q81 is Healthy only when both rate limiting and timing drift were tested.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Q81 tests 429/503 and median-TTFB drift (first vs last tenth, >= 20 samples); untested drift keeps Q81 below Healthy. Rainbet fails the gate (214 rate-limited responses), so every answer is Needs validation for that run. Audits saved before this change fail the gate until regenerated.
