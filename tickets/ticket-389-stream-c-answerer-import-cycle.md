# Ticket 389: Break the import cycle between the question runner and observed answerers

## Goal

Fix a defect found in QA of the Stream C work on 2026-10-06, before it is merged. Either module must import cleanly in a fresh interpreter, with no change in behaviour.

## Problem

`src/crawler_cli/technical_audit_questions.py` imported `OBSERVED_ANSWERERS` at its bottom while `src/crawler_cli/technical_audit_observed_answers.py` imported `Evidence`, `Answerer`, `Json` and three helpers from `technical_audit_questions`. In a fresh interpreter `from crawler_cli.technical_audit_observed_answers import OBSERVED_ANSWERERS` raised `ImportError` (partially initialized module).

## Evidence

`tests/test_stream_c_qa_fixes.py::test_observed_answerers_import_in_a_fresh_interpreter` runs that import in a subprocess and failed with the ImportError before the fix.

## Tasks

- [x] Move `Evidence`, `Answerer`, `Json`, `_profile_value`, `_path_and_query` and `_int_or_none` into the leaf module `src/crawler_cli/technical_audit_evidence.py`.
- [x] Import them from the leaf in both `technical_audit_questions` (which re-exports the same names, so existing imports keep working) and `technical_audit_observed_answers`.
- [x] Keep the registration of `OBSERVED_ANSWERERS` into `ANSWERERS` at the bottom of the runner.

## Definition of Done

- [x] The subprocess import test passes; `test_question_runner_registers_the_observed_answerers` shows every observed answerer is still registered.
- [x] Full test suite passes with no behaviour change.

## Status

proposed (Priority: **P2**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (regression tests in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
