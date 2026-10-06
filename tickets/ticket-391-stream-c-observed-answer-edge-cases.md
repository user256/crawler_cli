# Ticket 391: Tighten observed-answer edge cases

## Goal

Fix three small defects found in QA of the Stream C work on 2026-10-06, before it is merged.

## Problem

- `_host_exposure` in `src/crawler_cli/technical_audit_observed_answers.py` treated a `content_type` of `None` as HTML, so a `host-probe` `{host, status: 200, noindex: false}` for a non-HTML host became a Q27 Issue with a ticket.
- `_sitewide_external_links` stamped every Q43 row with `pages[0]["_provenance"]`, misattributing source and time when several `html-signals` collections are merged.
- `attach_observations` in `src/crawler_cli/audit_observations.py` iterated `existing.get("collections", [])` without a type guard, so a malformed prior `observations.collections` value raised `TypeError` instead of `ObservationError`.

## Evidence

`tests/test_stream_c_qa_fixes.py`: `test_q27_host_with_unknown_content_type_is_a_candidate_for_review_not_an_issue`, `test_q43_rows_carry_the_provenance_of_the_page_that_links` and `test_attach_observations_rejects_malformed_prior_collections` each failed before the fix.

## Tasks

- [x] An unknown content type is listed among the unread fields, which makes the host a candidate for review (Needs validation, no ticket) rather than an Issue. The Q27/Q77 finding fixtures now state `content_type: text/html`, and the exposure-inventory review finding now reads "not read: content_type, noindex" because that adapter reads headers only.
- [x] Each Q43 row carries the provenance of the first page that links to the target.
- [x] `attach_observations` raises `ObservationError` when the audit's `observations` is not an object or its `collections` is not a list of objects.

## Definition of Done

- [x] The three regression tests fail on the current code and pass after the fix; `test_q27_html_host_without_mitigation_is_still_an_issue` keeps the real Issue.
- [x] Full test suite passes.

## Status

proposed (Priority: **P3**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (regression tests in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
