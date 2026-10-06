# Ticket 371: Decode JSONB in Stream B report collectors

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`CrawlReports._fetch` returns JSONB columns (`canonical_urls_json`, `hreflang_json`, `headers_json`) as `str`. The Stream B collectors check `isinstance(..., list/dict)` and silently skip every row; unit fixtures use real lists/dicts, so tests pass.

## Evidence

On rainbet-20260925-v4: Q11 answered Healthy while 130 duplicate title/H1 clusters exist among indexable self-canonical pages; `hreflang_validation` found only 19 rows while decoded data gives 16,776 non-reciprocal, 14,115 noindex-target and 13,641 non-200-target edges (`hreflang-noindex` reported pass); 9,311 pages carry a Link canonical header that `stored_html_findings` never sees (Q71 exemption, Q73 header targets and Q94 canonical comparison inert).

## Tasks

- [x] Decode JSONB values in the Stream B collectors (`duplicate_metadata`, `hreflang_validation`, `stored_html_findings`, `nonhtml_search_assets`, `profile_indexability_pages`) or in one shared helper.
- [x] Add collector tests whose fake `_fetch` returns DB-shaped rows (JSON as `str`), so this class of bug fails in CI.
- [x] Re-run on rainbet-20260925-v4 and record the corrected counts.

## Definition of Done

- [x] Collector tests fail on the current code and pass after the fix.
- [x] Rainbet Q11, hreflang checks and header-canonical rows match a direct decoded query.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Verified on rainbet-20260925-v4: Q11 now finds 130 clusters; hreflang finds 16,776 non-reciprocal, 14,115 noindex-target and 13,641 non-200-target edges; 72 header/HTML canonical mismatches.
