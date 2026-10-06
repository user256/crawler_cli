# Ticket 378: Keep heavy stored-HTML reports out of the default report run

## Goal

Fix a defect found in QA of the Stream B (page indexability) work on 2026-10-06, before it is merged.

## Problem

Stream B added six reports to `_REPORT_NAMES`, so the flagless `crawler-cli report` now decompresses every stored page twice. Four tests in `tests/test_report_cli.py` fail because the fakes lack the new methods.

## Evidence

`pytest tests/test_report_cli.py`: 4 failures (`AttributeError: 'FakeReports' object has no attribute 'stored_html_findings'`).

## Tasks

- [x] Make the stored-HTML reports opt-in for `report` (or available only to `technical-audit`).
- [x] Update the fakes and tests.

## Definition of Done

- [x] Full test suite passes.
- [x] Flagless `report` does not scan stored HTML.
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

done (Priority kept). Branch feature/technical-audit-stream-b, commits a94d1f6 and ac01130; regression tests in tests/test_stream_b_qa_fixes.py. Audit-input reports are opt-in for `report`; fakes updated; report CLI tests pass.
