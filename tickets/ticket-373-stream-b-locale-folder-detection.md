# Ticket 373: Only treat real locale folders as locales in Q41

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

`hreflang_audit._locale_folder` accepts any 2–3 letter first path segment as a language, so `/aml` (anti-money-laundering) is read as locale `aml`.

## Evidence

All 19 Q41 rows on rainbet-20260925-v4 are `/aml` variants; Q41 is raised as an Issue with a ticket.

## Tasks

- [x] Recognise a folder as a locale only when it is a declared hreflang code in the run (or a profile locale list), not by shape alone.
- [x] Add fixtures for `/aml`, `/faq`, `/es/` and `/pt-br/`.

## Definition of Done

- [x] Rainbet Q41 no longer reports `/aml`.
- [x] A page in a genuine locale folder declaring another language is still a finding.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Rainbet Q41: /aml rows gone; 5 genuine rows remain (/ja, /pt, /ru, /tr, /zh homepages declare lang=en).
