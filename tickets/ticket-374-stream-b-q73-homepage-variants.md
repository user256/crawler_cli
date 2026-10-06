# Ticket 374: Exclude homepage variants from Q73

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

The canonical-to-homepage check excludes only the exact homepage. The rule excludes "the homepage and its variants" (query strings, `index.html`, tracking parameters).

## Evidence

All 3 Q73 rows on rainbet-20260925-v4 are `/?modal=…` homepage variants canonicalising to the homepage, raised as an Issue with a ticket.

## Tasks

- [x] Treat any URL whose path is the root (or a root index file) on the same host as a homepage variant.
- [x] Add fixtures.

## Definition of Done

- [x] Rainbet Q73 reports no homepage query variants.
- [x] A deep page canonicalising to the homepage is still a finding.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Rainbet Q73: 3 homepage-variant rows -> 0.
