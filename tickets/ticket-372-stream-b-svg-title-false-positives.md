# Ticket 372: Stop SVG titles and feed links tripping Q10 and Q12

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`inspect_stored_html` counts every `<title>` in the document, and the head-only regex matches `<title` and any `rel=alternate` link inside `<body>`. Inline SVG icons legitimately contain `<title>`; RSS/Atom alternates are not hreflang links.

## Evidence

On rainbet-20260925-v4, 9,467 of 10,852 pages are flagged `duplicate-title` and `head-only-element-in-body`, each raising an automatic ticket; the sampled page has 1 head title and 6 SVG icon titles.

## Tasks

- [x] Ignore `<title>` inside `<svg>` (and other foreign content) for both duplicate-title and head-only checks.
- [x] Treat a body `<link rel=alternate>` as head-only only when it carries `hreflang`.
- [x] Add fixtures for SVG icon titles and an RSS alternate.

## Definition of Done

- [x] Rainbet Q10/Q12 counts drop to pages with genuine duplicate or misplaced head elements.
- [x] Fixtures prove SVG titles and RSS alternates are not findings.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Rainbet Q10/Q12 rows: 9,467 -> 0.
