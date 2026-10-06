# Ticket 380: Make profile page facts run-scoped and meaningful

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`profile_indexability_pages` takes `in_sitemap` from the global `urls.is_from_sitemap`, counts inlinks from `frontier.parent_id` (one discovering parent per URL, so 0 or 1), and never supplies `is_navigation_target`.

## Evidence

Q78's top-decile inlink test is meaningless with 0/1 counts; a URL seen in a sitemap by any earlier run counts as in-sitemap; Q20 can never be complete.

## Tasks

- [x] Take sitemap membership from run-scoped sources (`run_url_sources` sitemap/robots_sitemap) and record when the run has no sitemap evidence.
- [x] Count inlinks from the run's `links_json` graph.
- [x] Supply a navigation-target flag (links inside header/nav) or record Q20 as permanently partial with the reason.

## Definition of Done

- [x] Q20/Q37/Q78 facts are run-scoped and inlink percentiles reflect the internal link graph.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Sitemap membership from run_url_sources (NULL when the run recorded none); inlinks from the run's links_json graph; navigation flag from header/nav xpaths.
