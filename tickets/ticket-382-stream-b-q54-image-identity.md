# Ticket 382: Make Q54 rows traceable to individual images

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`_semantic_figure_caption` repeats the page row once per uncaptioned image, so rows carry no image identity.

## Evidence

Q54 data tab shows duplicated page rows instead of the images.

## Tasks

- [x] Emit one row per uncaptioned main-content image with its src (bounded), or report pages with an image count.

## Definition of Done

- [x] Every Q54 row identifies the image (or the page and count) it represents.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. One Q54 row per uncaptioned image with its src (50 listed per page; the rest counted).
