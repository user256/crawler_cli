# Ticket 377: Separate locale markup rows from Q32 and restore review qualifications

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Stream B merged deterministic locale markup rows (missing/invalid html lang, lang/hreflang mismatch, locale-folder mismatch) into the `locale-html-lang` check, made it available whenever stored HTML exists, and removed `qualification="review_required"` from `locale-html-lang` and `near-duplicate-content` without explanation.

## Evidence

Q32's answerer reads every `locale-html-lang` row, so a `missing-html-lang` row becomes a content-language finding, and Q32 can turn Healthy with no signature evidence. Near-duplicate rows (Q21) now raise automatic tickets, and the audit ticket register changes.

## Tasks

- [x] Keep content-signature rows for Q32 and markup rows for Q8/Q41 distinguishable (separate kind filter or check), with each population's own availability and denominator.
- [x] Restore `review_required` on near-duplicate and signature evidence, or document why it is safe to remove.
- [x] Add tests for Q32 with only markup rows.

## Definition of Done

- [x] Q32 never counts markup rows and is Pending without signatures.
- [x] Q21 near-duplicates are review candidates again unless deliberately changed.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. locale-html-lang restored to signature rows with review_required; markup rows moved to metadata-basics (Q8) and hreflang-html-http (Q41); near-duplicate review_required restored. Registry Q8/Q41 evidence owners updated.
