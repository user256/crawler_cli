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

- [ ] Record a primary-content comparison with provenance, or keep raw-body differences as review-only evidence.
- [ ] Preserve collection qualifications across the adapter rather than silently promoting analyst observations.
- [ ] Test script/config/nonce-only changes, rotating bodies and real translated main content; retain actual status and redirect differences.

## Status

proposed (Priority: **P1**). Filed by post-merge QA, 2026-10-06.
Related existing tickets: 344, 409. This records a fix request; no product fix has been applied.
