# Ticket 386: Keep Q28, Q31 and locale probes below Healthy when a field was never recorded

## Goal

Fix a defect found in QA of the Stream C (render, probe and supplied evidence) work on 2026-10-06, before it is merged. A record missing a field the rule depends on must count as untested, so the answer is Needs validation or Pending, never Healthy.

## Problem

Three answerers in `src/crawler_cli/technical_audit_observed_answers.py` read an absent field as a clean one:

- `_external_links` tested the affiliate `rel` only when the key was present, so an `external-link-recheck` record `{source_url, target_url: "https://partner-casino.example/go", status: 200}` with no `rel` key counted as tested-clean and Q28 answered Healthy/No.
- `_verified_google_fetch` treated any one known flag as a full comparison and read the other two `None` flags as "not differing", so `verified-google-fetch` `{url, content_differs: false}` gave Q31 Healthy/No.
- `_locale_probes` silently skipped the Location and content checks when the fields were absent and still reached Healthy.

## Evidence

Before the fix, each of the records above produced `Healthy` / `No` on a complete-coverage fixture; `tests/test_stream_c_qa_fixes.py` reproduces all three.

## Tasks

- [x] `_external_links`: an affiliate link with no `rel` key is `UNTESTED` unless its status already fails.
- [x] `_verified_google_fetch`: a fetch is clean only when all three flags are `False`; a `True` flag is still a finding; anything else is `UNTESTED`.
- [x] `_locale_probes`: a probe with equal statuses is clean only when `baseline_location`, `variant_location` and `primary_content_differs` were recorded; otherwise it is untested and the note says so.
- [x] Correct the Q25 clean fixture in `tests/test_technical_audit_observed_answers.py` so it records every compared field, and document the field requirements in `docs/technical-audit-observations.md`.

## Definition of Done

- [x] Regression tests fail on the current code and pass after the fix (`test_q28_affiliate_link_without_a_rel_field_is_untested`, `test_q31_single_known_flag_is_not_a_full_comparison`, `test_q25_probe_without_location_or_content_fields_is_untested`, plus the "still reported" and Healthy guards beside them).
- [x] Full test suite passes; no answer becomes Healthy from absent, partial or zero-population evidence.

## Status

proposed (Priority: **P1**). Source: Stream C QA, 2026-10-06. Fix implemented on branch feature/technical-audit-stream-c-qa (regression tests in tests/test_stream_c_qa_fixes.py), awaiting QA re-review.
