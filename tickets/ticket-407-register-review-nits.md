# Ticket 407: Register publisher review nits

## Goal

Register publisher review nits.

## Problem

`--google-sheets-*` flags are silently ignored when only `--publish-ticket-register` is set; `test_analyst_only_candidates…` expects a locale-redirect request that production never emits; `test_one_metadata_finding…` asserts `<= 1` where production yields 0 because every shared detector is check-level `analyst_only`; `run_context["manual_review_evidence"]` is dropped silently when it is not a mapping (a JSONB-as-text value would make every keyed question unavailable).

## Evidence

QA review of feature/full-manual-review-audit, findings 5-7.

## Tasks

- [ ] Reject the ignored flags; align the two tests with production; decode or diagnose a non-mapping manual_review_evidence value.

## Definition of Done

- [ ] Each item closed or re-filed.

## Status

proposed (Priority: **P3**). Source: master reconciliation QA, 2026-10-06.
