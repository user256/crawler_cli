# Ticket 402: Feed the external-link-integrity control from the recheck rows the audit stores

## Goal

Feed the external-link-integrity control from the recheck rows the audit stores.

## Problem

`CONTROL_DETECTORS` mapped `external-link-integrity` to a detector id `external-link-rechecks` that `build_technical_audit` never emitted; recheck rows lived only under `audit["external_link_rechecks"]`. The control was therefore always unavailable, every client register carried the input-request ticket 'Authorise an external-link recheck', and a run whose rechecks found dead destinations produced no ticket for them.

## Evidence

QA review of feature/full-manual-review-audit, finding 1; `tests/test_technical_audit_contract.py` passed only by fabricating the detector id.

## Tasks

- [x] Emit an `external-link-rechecks` detector: hard failures (http/dns/tls/transport) are evidence rows; pass only on a complete, clean recheck; partial when bounded.
- [x] Contract-level regression tests for unavailable / finding / pass / bounded.

## Definition of Done

- [x] A run with a failed recheck tickets the failure and no longer asks for a recheck.

## Status

implemented (local) (Priority: **P1**). Source: master reconciliation QA, 2026-10-06.
