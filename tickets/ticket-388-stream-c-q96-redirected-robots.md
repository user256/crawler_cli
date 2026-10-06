# Ticket 388: Treat a redirected robots.txt without a body as unknown in Q96

## Goal

Fix a defect found in QA of the Stream C work on 2026-10-06, before it is merged. A robots.txt that was never read must not be parsed as an empty, allow-all file.

## Problem

`_ai_crawler_policy` in `src/crawler_cli/technical_audit_observed_answers.py` treated only a 5xx and a bodiless 2xx as unread. A 3xx `robots-txt` record with no body parsed as an empty file (allow-all), so `{host, status: 301}` gave Q96 Issue against a disallow policy, and a 401/403/429 did the same.

## Evidence

`tests/test_stream_c_qa_fixes.py::test_q96_robots_without_a_readable_body_is_unknown` reproduces the Issue for a 301, a 302 carrying the redirect page as its body, and a 403.

## Tasks

- [x] Parse a body only from a 2xx record that carries one.
- [x] Keep a 404 (and 410) as "no robots.txt", which allows everything (RFC 9309).
- [x] Treat every other response (a redirect, a bodiless 2xx, any other 4xx, a 5xx, no status) as unread: the host is listed in the note and the answer cannot become Healthy.
- [x] Document the status rules in `docs/technical-audit-observations.md`.

## Definition of Done

- [x] The regression test fails on the current code and passes after the fix; `test_q96_definitive_404_still_means_no_robots_file` and the existing 404/503 test keep their behaviour.
- [x] Full test suite passes.

## Status

proposed (Priority: **P1**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (regression tests in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
