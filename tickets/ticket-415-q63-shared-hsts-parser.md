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

- [ ] Reuse parse_strict_transport_security and its validity/errors when evaluating Q63.
- [ ] Keep missing preload membership and OCSP evidence unknown; do not fix parsing by claiming those probes ran.
- [ ] Test whitespace, quoted values, duplicate max-age, malformed directives and valid strong/weak policies through both stored and supplied observation paths.

## Status

proposed (Priority: **P2**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 362, 409. This records a fix request; no product fix has been applied.
