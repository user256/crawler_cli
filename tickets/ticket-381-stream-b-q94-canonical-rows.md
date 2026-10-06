# Ticket 381: Report header/HTML canonical mismatches as their own finding

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Stream B appends `html-header-canonical-mismatch` rows to `indexability_conflicts`, whose audit-log action says "Conflicting indexability directives" with a robots-directive fix.

## Evidence

Canonical mismatches would be ticketed with robots-directive wording.

## Tasks

- [x] Give canonical mismatches their own action text (or check), and keep Q94 reading both populations.

## Definition of Done

- [x] Q94 rows and audit-log actions name the canonical conflict correctly.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Header/HTML canonical mismatches are canonical-declarations rows; Q94 reads both populations; no robots-conflict audit-log action.
