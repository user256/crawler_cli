# Ticket 379: Scan stored HTML once, without loading the whole run into memory

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`stored_html_findings` and `semantic_html_facts` each call `fetch_pages_for_embeddings`, which loads every stored page of the run into memory.

## Evidence

Rainbet (10,852 pages): technical-audit took 8m21s with a 3.9 GB peak RSS.

## Tasks

- [x] Stream pages with a server-side cursor (`AsyncpgStore.iter_run_html` exists on the Stream C branch) and compute both fact sets in one pass.
- [x] Record peak memory and time on Rainbet before and after.

## Definition of Done

- [x] One decompression pass per page.
- [x] Peak memory no longer scales with total stored HTML.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. One streamed pass serves stored-html, semantic-html and soft-404. Rainbet peak RSS 3.9 GB -> 1.2 GB (run time unchanged, ~8.5 min).
