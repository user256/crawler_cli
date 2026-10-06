# Ticket 387: Do not raise Q102 when robots blocking was never checked

## Goal

Fix a defect found in QA of the Stream C work on 2026-10-06, before it is merged. Q102 raises an automatic client ticket only when the evidence proves that a public utility URL has neither control.

## Problem

`_utility_paths` in `src/crawler_cli/technical_audit_observed_answers.py` fired `noindex is not True and robots_blocked is not True` when `robots_blocked` was absent. A `utility-path-probe` record `{path_class: "public-utility", status: 200, noindex: false}` gave Q102 Issue with a ticket saying "no noindex or robots.txt control" although robots.txt was never checked.

## Evidence

`tests/test_stream_c_qa_fixes.py::test_q102_public_utility_path_with_one_unknown_control_is_untested` reproduces the Issue with each of `noindex` or `robots_blocked` missing or `null`.

## Tasks

- [x] A public-utility record is `UNTESTED` unless both `noindex` and `robots_blocked` are known.
- [x] Issue only when both are known `False`; the "unreadable noindex" finding only when both are known `True`.
- [x] Document in `docs/technical-audit-observations.md` that a public-utility path needs both fields recorded.

## Definition of Done

- [x] The regression test fails on the current code and passes after the fix; `test_q102_public_utility_path_with_both_controls_absent_is_an_issue` keeps the real Issue.
- [x] Full test suite passes; Q102 never drafts a ticket from an unchecked control.

## Status

proposed (Priority: **P1**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (regression tests in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
