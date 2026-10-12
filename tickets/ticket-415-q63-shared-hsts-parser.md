# Ticket 415: Use the shared HSTS parser in the Q63 answerer

## Goal

Restore the evidence and coverage contract for Q63 after PR #118.

## Problem

The Q63 answerer disagrees with the repository's existing HSTS parser and can both raise false issues and report invalid policy as Healthy.

## Cause and evidence

`_hsts_ocsp` reimplements directive parsing using startswith("max-age=") and takes the first value. It ignores whitespace accepted by the shared parser and duplicate-directive errors.

With preload_status=preloaded and ocsp_stapled=true: `max-age = 31536000; includeSubDomains; preload` is valid according to parse_strict_transport_security but Q63 reports Issue. `max-age=31536000; max-age=0; includeSubDomains; preload` is rejected by the parser as duplicate_directive:max-age but Q63 reports Healthy.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `415` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [x] Reuse parse_strict_transport_security and its validity/errors when evaluating Q63.
- [x] Keep missing preload membership and OCSP evidence unknown; do not fix parsing by claiming those probes ran.
- [x] Test whitespace, quoted values, duplicate max-age, malformed directives and valid strong/weak policies through both stored and supplied observation paths.

## Status

done (Priority: **P2**). Fixed on branch `fix/postmerge-qa-tls`, 2026-10-07.

Fix: `_hsts_ocsp` in `technical_audit_observed_answers.py` now calls `transport_security.parse_strict_transport_security`, and the second parser is gone. If the header is missing, Q63 reports "no Strict-Transport-Security header". If it is invalid, Q63 reports "invalid Strict-Transport-Security header (<parser errors>)" and ignores its directives, as a user agent does. If it is valid, Q63 checks max-age against `HSTS_PRELOAD_MIN_MAX_AGE` and checks for includeSubDomains and preload. The preload-membership and OCSP handling is unchanged: a missing value stays unknown and keeps Q63 below Healthy.

Tests: `tests/test_tls_final_response_identity.py` runs 11 header cases through both the supplied-record path and the stored path (`transport_security_report` -> `tls_probe_records`): whitespace, a quoted value, upper case, a duplicate max-age, a non-numeric max-age, a missing max-age, `includeSubDomains=1`, a weak max-age, and a missing includeSubDomains or preload. The stored path is never Healthy because it has no preload or OCSP evidence. In `reproduce.py`, key 415 now gives Healthy for the whitespace header and Issue for the duplicate max-age.
