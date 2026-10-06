# Ticket 390: Say truthfully how Q46 footer evidence is collected

## Goal

Fix a documentation defect found in QA of the Stream C work on 2026-10-06, before it is merged. The observations document must not promise evidence that no collector writes.

## Problem

`docs/technical-audit-observations.md` said the `render-parity` collection carries `footer.raw_links` and `footer.rendered_links` for Q46, but `RenderParityComparison.as_dict` in `src/crawler_cli/compare_renders.py` never emits a `footer` key, so `--render-comparison` output always leaves Q46 Pending.

## Evidence

`tests/test_stream_c_qa_fixes.py::test_q46_stays_pending_on_compare_renders_output_without_footer_fields` feeds a compare-renders payload through `collection_from_render_comparison` and shows Q46 Pending with the record counted as untested.

## Tasks

- [x] Correct the document: `--render-comparison` answers Q85 only; the Q46 footer fields need a hand-written or future collection.
- [x] Add the Pending guard test above. Footer extraction is deliberately not added to compare-renders.

## Definition of Done

- [x] The document and the kinds table name the gap.
- [x] The guard test passes; full test suite passes.

## Status

proposed (Priority: **P3**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (guard test in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
