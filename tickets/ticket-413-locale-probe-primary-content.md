# Ticket 413: Compare primary content rather than raw HTML bytes for Q25

## Goal

Restore the evidence and coverage contract for Q25 after PR #118.

## Problem

The adapter raises a primary-content defect when only a script in the head changes and all visible content stays identical.

## Cause and evidence

`_content_differs` equates a changed whole-response SHA-256 with changed primary content. It discards the collector's content comparison and review qualification. A stable repeated baseline does not establish that the changed bytes are primary content.

Real collector fixture: same status, URL, html_lang and 100 repeated sentences in main; only window.analyticsLocale changes from en to es inside a head script. Collector differences_from_no_header=[]; adapter and runner nevertheless produce Issue, ticket=true, `primary content differs`.

Reproduced on merged master `72629af137e0803aface1f4ce94a9a18ba7f0eb1`.
Run `PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py` from the repository root. See result key `413` in [captured results](./qa-new-audit-2026-10-06/results.json).

## Tasks and acceptance criteria

- [x] Record a primary-content comparison with provenance, or keep raw-body differences as review-only evidence.
- [x] Preserve collection qualifications across the adapter rather than silently promoting analyst observations.
- [x] Test script/config/nonce-only changes, rotating bodies and real translated main content; retain actual status and redirect differences.

## Status

done (Priority: **P1**). Fixed on branch `fix/postmerge-qa-locale`, 2026-10-07.

Fix: the collector records `primary_content_sha256` with `primary_content_basis` (visible text of `<main>`/`role=main`,
else `<body>`; script, style, noscript and template text and all attributes ignored). The adapter sets
`primary_content_differs` only from that hash, and only when baseline, repeated header-less control and variant all
resolved, the control matched the baseline and the basis matches; otherwise None (untested). Whole-response byte
differences are kept as `raw_body_differs`, review-only: the answerer notes them but never counts them. The collector's
qualification is carried on every record as `collection_qualification`. Status and Location differences are unchanged.
Regression tests in `tests/test_locale_probe_verdicts.py`: head-script locale, inline JSON config, rotating nonce/style,
rotating main content (unknown, not Issue), translated main content (Issue), `<body>` fallback, and legacy evidence
without a primary-content hash.

Decision: a measured, control-stable primary-content difference stays a confirmed Q25 Issue, as the question's
"Issue if" rule says; content comparison is unknown (not Healthy, not Issue) whenever any input is missing or volatile.
