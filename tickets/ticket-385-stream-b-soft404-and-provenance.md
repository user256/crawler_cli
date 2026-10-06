# Ticket 385: Tighten the soft-404 and discovery-provenance collectors Stream B added

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged. These two collectors serve Stream A questions Q42 (ticket 349) and Q82 (ticket 284).

## Problem

`soft404_error_routes` matches `404|not found|error page` anywhere in the tag-stripped source of every 200 page (scripts, prices and footer copy included) and loads all stored HTML a third time. `discovery_source_provenance` takes sitemap membership from the global `urls.is_from_sitemap` and "found from an internal link" from `frontier.parent_id`, which records only the first discovering parent.

## Evidence

Signature `\b(?:404|page\s+not\s+found|not\s+found|error\s+page)\b` over the whole source; rainbet-20260925-v4 records no run-scoped sitemap sources and frontier depth is at most 1.

## Tasks

- [x] Match the soft-404 signature on the title and H1 (and main heading text) only, and share the single stored-HTML pass (ticket 379).
- [x] Take sitemap membership from run-scoped `run_url_sources` and internal discovery from the run's link graph; report the check unavailable when the run recorded no sitemap sources.

## Definition of Done

- [x] A `404` in body copy or scripts is not a soft-404 candidate; a 200 page titled "Page not found" is.
- [x] Q82 rows are run-scoped and Pending when sitemap sources were not recorded.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Soft-404 matches title/H1 only; provenance is run-scoped and unavailable when the run recorded no sitemap sources (Rainbet: none recorded, so Q82 is Pending).
