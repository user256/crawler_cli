# Ticket 375: Detect X-Robots-Tag by header name in Q87

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`nonhtml_search_assets` searches header values for the string `x-robots-tag`, never the header names, so a document that sends `X-Robots-Tag` is still reported as missing it.

## Evidence

Reproduced with a PDF row whose headers are `{"x-robots-tag": "noindex"}`: it is reported.

## Tasks

- [x] Check header names case-insensitively for `x-robots-tag`, and parse the `link` header for `rel=canonical`.
- [x] Add collector tests (with JSON headers as `str`, see 371).

## Definition of Done

- [x] A document with either header is not a finding; one with neither is.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Header names are read case-insensitively; Link canonical parsed from the link header.
