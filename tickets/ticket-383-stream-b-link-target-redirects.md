# Ticket 383: Detect redirecting link targets by final URL, and compare canonicals normalised

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Stream B widened `internal_link_quality` (shared by Q22, Q39 and its new Q72 answerer) to report redirect, noindex and non-canonical targets. Redirects are detected as `final_status_code BETWEEN 300 AND 399`, but a followed redirect stores its destination's status; non-canonical targets compare canonical and URL as raw strings; an empty anchor still masks every other issue in the CASE.

## Evidence

rainbet-20260925-v4: 0 snapshots have a 3xx final or initial status while 5 have `final_url_id <> url_id`, so `redirect_target` and Q72 never fire; `https://rainbet.com` vs `https://rainbet.com/` counts as non-canonical.

## Tasks

- [x] Classify a target as redirecting when `final_url_id <> url_id` (or the initial status is 3xx).
- [x] Normalise both sides before the canonical comparison.
- [x] Report each issue independently of an empty anchor.
- [x] Remove the Q39 scope note once its branches are tested; update tickets 343 (Q22), 348 (Q39) and 351 (Q72).

## Definition of Done

- [x] Q72 and Q22 find redirecting targets on a fixture whose redirect has a 200 final status.
- [x] No slash-only canonical difference is reported.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Redirects detected by final URL (origin vs its / form excluded); one row per issue; canonicals compared without a trailing slash. Rainbet: 49 genuine redirecting targets, Q72 0 false rows.
