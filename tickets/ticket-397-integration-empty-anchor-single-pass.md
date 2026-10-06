# Ticket 397: Collect empty-anchor facts in the shared stored-HTML pass, bounded per page

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Stream A's `empty_anchor_links` report loaded every stored page into memory with `fetch_pages_for_embeddings`, parsed each page a second time, and wrote one row per internal anchor into the audit JSON (millions of rows on a large run). It was also in the default flagless `report` run, re-opening tickets 378 and 379.

## Evidence

Stream A QA review, finding 3; ticket 378/379 regressions.

## Tasks

- [x] Collect in `_stored_html_pass` (streamed, once per run).
- [x] Emit one row per page: internal anchor count plus up to 100 text-less anchors with their image alts.
- [x] Make `crawl-depth-pages`, `performance-pages` and `empty-anchor-links` opt-in for `report`; `technical-audit` still collects them.
- [x] Follow-up: share one parsed soup across the stored-HTML detectors instead of parsing per detector.

## Definition of Done

- [x] Audit JSON grows with pages, not links.
- [x] Flagless `report` does not parse stored HTML.
- [x] Single-pass test covers the new rows.

## Status

implemented (local); shared-soup follow-up open (Priority: **P1**). Source: stream integration QA, 2026-10-06.
